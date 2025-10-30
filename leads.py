# leads.py
"""
Сбор лидов по штату из внешних источников.
Сейчас: только Google Places API (New).

Логика:
1. по штату создаём/получаем лист в ClickUp (делает clickup_client);
2. забираем существующие задачи из этого листа, чтобы не плодить дубли;
3. идём в Google Places API (New) и собираем клиники по запросу "dental clinic in <STATE>, USA";
4. по каждой найденной создаём/апдейтим задачу в ClickUp.

Если Google выключен / не включен биллинг / не тот API → просто вернём пустой список,
но бот всё равно пришлёт понятный отчёт.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import requests

from config import settings
from clickup_client import clickup_client, READY_STATUS

log = logging.getLogger("leads")

# какие типы/категории будем спрашивать у гугла
GOOGLE_QUERY_TEMPLATE = "dental clinic in {state}, USA"

# сколько максимум заведений за раз вытаскивать (Places API New даёт пагинацию)
GOOGLE_PAGE_SIZE = 20


def _existing_keys_for_list(list_id: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    """
    Возвращает 3 словаря по уже существующим лидам:
      - by_web[website] = task_id
      - by_phone[phone] = task_id
      - by_sig["NAME|CITY"] = task_id     (на всякий — сигнатура по названию и городу)
    Нужно, чтобы не плодить дубли.
    """
    tasks = clickup_client.get_leads_from_list(list_id)  # уже нормализованные словари
    by_web: Dict[str, str] = {}
    by_phone: Dict[str, str] = {}
    by_sig: Dict[str, str] = {}

    for t in tasks:
        tid = str(t.get("task_id") or t.get("id") or "")
        name = (t.get("clinic_name") or t.get("name") or "").strip()
        city = (t.get("city") or "").strip()
        website = (t.get("website") or "").strip()
        phone = (t.get("phone") or "").strip()

        if website:
            by_web[website.lower()] = tid
        if phone:
            by_phone[phone] = tid
        if name:
            sig = f"{name.lower()}|{city.lower()}"
            by_sig[sig] = tid

    return by_web, by_phone, by_sig


# ---------------------------------------------------------------------------
# Google Places (New)
# ---------------------------------------------------------------------------

def _google_places_new_search(state: str) -> List[Dict[str, Any]]:
    """
    Обращается к Places API (New): https://places.googleapis.com/v1/places:searchText
    Возвращает список «сырых» places.
    """
    api_key = settings.GOOGLE_PLACES_API_KEY
    if not api_key:
        log.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.websiteUri,places.nationalPhoneNumber,places.primaryType,"
            "places.location"
        ),
    }
    body = {
        "textQuery": GOOGLE_QUERY_TEMPLATE.format(state=state),
        "pageSize": GOOGLE_PAGE_SIZE,
        # можно ещё languageCode/locationBias/regionCode — пока не усложняем
    }

    try:
        r = requests.post(url, headers=headers, json=body, timeout=15)
    except Exception as e:
        log.warning("google new places request error: %s", e)
        return []

    if r.status_code != 200:
        log.warning("google places new non-200: %s %s", r.status_code, r.text[:200])
        return []

    data = r.json()
    places = data.get("places", [])
    log.info("google (new) returned %s places for %s", len(places), state)
    return places


def _normalize_place(place: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводим гугловский place к нашей структуре для ClickUp.
    """
    name = (place.get("displayName", {}) or {}).get("text", "") or ""
    address = place.get("formattedAddress") or ""
    website = place.get("websiteUri") or ""
    phone = place.get("nationalPhoneNumber") or ""
    primary_type = place.get("primaryType") or ""

    # попробуем вынуть город из адреса (очень грубо)
    city = ""
    if address and "," in address:
        # "123 St, New York, NY 10001, USA"
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2:
            city = parts[-3] if len(parts) >= 3 else parts[-2]

    return {
        "clinic_name": name,
        "address": address,
        "city": city,
        "website": website,
        "phone": phone,
        "source": "google-places-new",
        "status": READY_STATUS,
        "category": primary_type,
    }


# ---------------------------------------------------------------------------
# Публичная точка для бота
# ---------------------------------------------------------------------------

def upsert_leads_for_state(state: str) -> Dict[str, Any]:
    """
    Основной вход из telegram_bot.py
    Возвращает отчёт:
        {
          "found": int,
          "created": int,
          "skipped": int,
          "list_id": str,
          "stats": {...}  # что вернули из clickup_client для сводки
        }
    """
    # 1. лист под штат
    list_id = clickup_client.get_or_create_list_for_state(state)
    log.info("start collecting for %s -> list %s", state, list_id)

    # 2. существующие лиды
    by_web, by_phone, by_sig = _existing_keys_for_list(list_id)

    # 3. берём из гугла
    raw_places = _google_places_new_search(state)

    found = len(raw_places)
    created = 0
    skipped = 0

    for p in raw_places:
        lead = _normalize_place(p)

        # простейшая дедупликация
        website = (lead.get("website") or "").lower()
        phone = (lead.get("phone") or "").strip()
        sig = f"{lead.get('clinic_name','').lower()}|{lead.get('city','').lower()}"

        if website and website in by_web:
            skipped += 1
            continue
        if phone and phone in by_phone:
            skipped += 1
            continue
        if sig and sig in by_sig:
            skipped += 1
            continue

        # создаём/апдейтим задачу в ClickUp
        clickup_client.upsert_lead(list_id, lead)
        created += 1

    # 4. ещё раз берём сводку по листу (то, что ты показываешь в telegram)
    leads_after = clickup_client.get_leads_from_list(list_id)
    total = len(leads_after)
    with_email = sum(1 for l in leads_after if l.get("email"))
    no_email = total - with_email
    ready = sum(1 for l in leads_after if l.get("status") == READY_STATUS)
    sent = sum(1 for l in leads_after if l.get("status") == "SENT")

    return {
        "found": found,
        "created": created,
        "skipped": skipped,
        "list_id": list_id,
        "stats": {
            "total": total,
            "with_email": with_email,
            "no_email": no_email,
            "ready": ready,
            "sent": sent,
            "remain": max(0, with_email - sent),
        },
    }
