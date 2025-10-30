# leads.py
import os
import logging
from typing import Dict, Any, List, Tuple, Optional
import requests

from clickup_client import clickup_client

log = logging.getLogger("leads")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

# сколько страниц гугла максимум тащим за один /collect
MAX_GOOGLE_PAGES = int(os.getenv("GOOGLE_PLACES_MAX_PAGES", "5"))

# что ищем — можно будет расширить
GOOGLE_BASE_QUERY = "dentist NY"   # потом можно подставлять штат


def _google_search_places(state: str) -> List[Dict[str, Any]]:
    """
    Ищем клиники в Google Places (New), с пагинацией.
    Возвращаем список raw places.
    """
    if not GOOGLE_PLACES_API_KEY:
        log.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        # чтобы в ответе сразу был сайт/телефон, просим нужные поля
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.websiteUri,places.internationalPhoneNumber"
        ),
    }

    # мы можем собирать чуть точнее по штату, но пока — как было
    text_query = f"dentist {state}"

    body: Dict[str, Any] = {
        "textQuery": text_query,
    }

    all_places: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    page = 0

    while page < MAX_GOOGLE_PAGES:
        req_body = dict(body)
        if page_token:
            req_body["pageToken"] = page_token

        resp = requests.post(url, headers=headers, json=req_body, timeout=30)
        data = resp.json()

        if resp.status_code != 200:
            log.warning("google textsearch status=%s data=%s", resp.status_code, data)
            break

        places = data.get("places", [])
        all_places.extend(places)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        page += 1

    log.info("google (new) returned %s places for %s", len(all_places), state)
    return all_places


def _google_place_details(place_id: str) -> Dict[str, Any]:
    """
    Подтягиваем детали по place_id — иногда в searchText их нет.
    """
    if not GOOGLE_PLACES_API_KEY:
        return {}

    # Сразу просим только нужные поля
    fields = "id,displayName,formattedAddress,websiteUri,internationalPhoneNumber"
    url = f"https://places.googleapis.com/v1/{place_id}"
    params = {
        "key": GOOGLE_PLACES_API_KEY,
        "fields": fields,
    }
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        log.warning("google details %s -> %s %s", place_id, r.status_code, r.text[:200])
        return {}
    return r.json()


def _normalize_place_to_lead(place: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводим гугловский place к нашему формату для ClickUp.
    """
    name = (place.get("displayName", {}) or {}).get("text") or place.get("name") or "Unknown"
    website = place.get("websiteUri") or ""
    phone = place.get("internationalPhoneNumber") or ""
    # соцсетей гугл не отдаёт — их будем тащить позже из Yelp/Zocdoc/чего-то ещё
    return {
        "name": name,
        "email": "",          # гугл не отдаёт
        "website": website,
        "facebook": "",
        "instagram": "",
        "linkedin": "",
        "phone": phone,
    }


def upsert_leads_for_state(state: str) -> Dict[str, Any]:
    """
    Главная функция, которую вызывает /collect.
    Создаём/обновляем всех, кого нашли, и возвращаем отчёт.
    """
    list_id = clickup_client.get_or_create_list_for_state(state)
    log.info("start collecting for %s -> list %s", state, list_id)

    # 1. тащим гугл
    raw_places = _google_search_places(state)

    created = 0
    skipped = 0

    for p in raw_places:
        lead = _normalize_place_to_lead(p)

        # если вдруг в searchText не было сайта/телефона — попробуем дотянуть
        if not lead["website"] or not lead["phone"]:
            pid = p.get("id")
            if pid:
                det = _google_place_details(pid)
                if det:
                    if not lead["website"]:
                        lead["website"] = det.get("websiteUri") or ""
                    if not lead["phone"]:
                        lead["phone"] = det.get("internationalPhoneNumber") or ""

        # на этом шаге у нас всё ещё может не быть email — это нормально
        clickup_client.upsert_lead(list_id, lead)
        created += 1

    # отчёт
    total_in_list = len(clickup_client.get_leads_from_list(list_id))
    report = {
        "found": len(raw_places),
        "created": created,
        "skipped": skipped,
        "total_in_list": total_in_list,
        "state": state,
    }
    return report
