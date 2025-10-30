# leads.py
import logging
import re
import time
from typing import Any, Dict, List, Optional

import requests

from config import settings
from clickup_client import (
    clickup_client,
    READY_STATUS,
    NEW_STATUS,
)

logger = logging.getLogger("leads")


GOOGLE_PLACES_API_KEY = getattr(settings, "GOOGLE_PLACES_API_KEY", "").strip()

# простейшая нормализация телефона, чтобы можно было сравнивать
_phone_clean_re = re.compile(r"\D+")


def _clean_phone(p: Optional[str]) -> str:
    if not p:
        return ""
    return _phone_clean_re.sub("", p)


def _google_places_text_search(state: str) -> List[Dict[str, Any]]:
    """
    Идём в Google Places Text Search и достаём все «dentist in {state}, USA».
    Возвращаем список place_id + базовые данные.
    """
    if not GOOGLE_PLACES_API_KEY:
        logger.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return []

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": f"dentist in {state}, USA",
        "key": GOOGLE_PLACES_API_KEY,
    }

    results: List[Dict[str, Any]] = []
    page = 1
    while True:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            logger.warning("google textsearch status=%s data=%s", status, data)
            break

        items = data.get("results", [])
        results.extend(items)

        next_token = data.get("next_page_token")
        if not next_token:
            break

        # у Places есть задержка между страницами
        time.sleep(2)
        params["pagetoken"] = next_token
        page += 1
        # ограничимся 3 страницами, чтобы не ушатать лимит
        if page > 3:
            break

    return results


def _google_place_details(place_id: str) -> Dict[str, Any]:
    """
    Берём подробности по place_id, чтобы достать сайт и телефон.
    """
    if not GOOGLE_PLACES_API_KEY:
        return {}

    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "key": GOOGLE_PLACES_API_KEY,
        # нам нужен хотя бы телефон и сайт
        "fields": "name,formatted_phone_number,website",
    }
    resp = requests.get(url, params=params, timeout=15)
    data = resp.json()
    if data.get("status") != "OK":
        return {}
    return data.get("result") or {}


def _existing_keys_for_list(list_id: str):
    """
    Загружаем уже существующие лиды и строим 3 множества:
    - по названию
    - по телефону
    - по сайту
    чтобы не создавать дубли
    """
    tasks = clickup_client.get_leads_from_list(list_id)

    by_name = set()
    by_phone = set()
    by_site = set()

    for t in tasks:
        name = (t.get("clinic_name") or "").strip().lower()
        if name:
            by_name.add(name)

        phone = _clean_phone(t.get("phone"))
        if phone:
            by_phone.add(phone)

        site = (t.get("website") or "").strip().lower()
        if site:
            by_site.add(site)

    return by_name, by_phone, by_site, tasks


def upsert_leads_for_state(state: str) -> Dict[str, Any]:
    """
    Главная функция: вызывается из telegram_bot.
    1. гарантируем лист
    2. тянем из гугла
    3. создаём новых
    4. отдаём краткий отчёт
    """
    state = state.upper()
    list_id = clickup_client.get_or_create_list_for_state(state)

    found = 0
    created = 0
    skipped = 0

    # что уже есть в листе
    by_name, by_phone, by_site, existing_tasks = _existing_keys_for_list(list_id)

    # 1. гугл
    google_places = _google_places_text_search(state)
    logger.info("google returned %d places for %s", len(google_places), state)

    for place in google_places:
        found += 1
        name = (place.get("name") or "").strip()
        if not name:
            skipped += 1
            continue

        # если такое имя уже есть — дубликат
        if name.lower() in by_name:
            skipped += 1
            continue

        place_id = place.get("place_id")
        details = _google_place_details(place_id) if place_id else {}

        website = (details.get("website") or "").strip()
        phone = _clean_phone(details.get("formatted_phone_number"))

        # проверим по сайту
        if website and website.lower() in by_site:
            skipped += 1
            continue

        # проверим по телефону
        if phone and phone in by_phone:
            skipped += 1
            continue

        # создаём задачу
        status = READY_STATUS if website else NEW_STATUS
        clickup_client.create_lead_task(
            list_id=list_id,
            clinic_name=name,
            website=website,
            email_=None,  # email ты сам будешь вписывать
            phone=phone,
            signature=None,
            status=status,
        )

        created += 1
        by_name.add(name.lower())
        if website:
            by_site.add(website.lower())
        if phone:
            by_phone.add(phone)

    # можно здесь же будет довесить Yelp/Zocdoc/Healthgrades

    # после апдейта — перечитаем лист для статистики
    final_tasks = clickup_client.get_leads_from_list(list_id)
    total = len(final_tasks)
    with_email = sum(1 for t in final_tasks if t.get("email"))
    no_email = total - with_email
    ready = sum(1 for t in final_tasks if t.get("status") == READY_STATUS)
    sent = sum(1 for t in final_tasks if t.get("status") == "SENT")
    remaining = sum(1 for t in final_tasks if (t.get("email") and t.get("status") != "SENT"))

    return {
        "state": state,
        "list_id": list_id,
        "found": found,
        "created": created,
        "skipped": skipped,
        "total_in_list": total,
        "with_email": with_email,
        "no_email": no_email,
        "ready": ready,
        "sent": sent,
        "remaining_unsent": remaining,
    }
