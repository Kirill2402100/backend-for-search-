# leads.py
import os
import logging
from typing import Dict, Any, List, Optional
import requests

from clickup_client import clickup_client

log = logging.getLogger("leads")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

# что ищем по умолчанию — ты можешь поменять на что-то другое
BASE_QUERY_TEMPLATE = "dentist {state}"


def _google_search_all_places(state: str) -> List[Dict[str, Any]]:
    """
    Делаем places:searchText в Google Places (New) и забираем ВСЕ страницы,
    пока у гугла есть nextPageToken.
    """
    if not GOOGLE_PLACES_API_KEY:
        log.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return []

    url = "https://places.googleapis.com/v1/places:searchText"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        # сразу просим то, что нам потенциально нужно
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.websiteUri,places.internationalPhoneNumber"
        ),
    }

    text_query = BASE_QUERY_TEMPLATE.format(state=state)

    base_body: Dict[str, Any] = {
        "textQuery": text_query,
    }

    all_places: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    page_num = 0

    while True:
        body = dict(base_body)
        if page_token:
            body["pageToken"] = page_token

        resp = requests.post(url, headers=headers, json=body, timeout=30)
        data = resp.json()

        if resp.status_code != 200:
            log.warning("google textsearch status=%s data=%s", resp.status_code, data)
            break

        places = data.get("places", [])
        all_places.extend(places)

        page_num += 1
        page_token = data.get("nextPageToken")

        if not page_token:
            break  # страниц больше нет

    log.info("google (new) returned %s places for %s", len(all_places), state)
    return all_places


def _google_place_details(place_id: str) -> Dict[str, Any]:
    """
    Дотягиваем детали по place_id — там бывает website и телефон.
    """
    if not GOOGLE_PLACES_API_KEY:
        return {}

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


def _normalize_place(place: Dict[str, Any]) -> Dict[str, Any]:
    """
    Приводим плейс к нашему “лиду”.
    """
    name = (place.get("displayName") or {}).get("text") or place.get("name") or "Unknown"
    website = place.get("websiteUri") or ""
    phone = place.get("internationalPhoneNumber") or ""

    return {
        "name": name,
        "email": "",          # гугл не отдаёт
        "website": website,
        "facebook": "",       # сюда будем писать из других источников
        "instagram": "",
        "linkedin": "",
        "phone": phone,
    }


def upsert_leads_for_state(state: str) -> Dict[str, Any]:
    """
    Главная функция, которую вызывает /collect STATE.
    1) гарантируем лист
    2) тянем все страницы из Google Places (New)
    3) по каждому месту — если нужно — дотягиваем детали
    4) upsert в ClickUp
    5) отдаём отчёт
    """
    list_id = clickup_client.get_or_create_list_for_state(state)
    log.info("start collecting for %s -> list %s", state, list_id)

    raw_places = _google_search_all_places(state)

    created = 0
    skipped = 0

    for place in raw_places:
        lead = _normalize_place(place)

        # если в поиске не было сайта/телефона — пробуем дотянуть
        if (not lead["website"]) or (not lead["phone"]):
            pid = place.get("id")
            if pid:
                det = _google_place_details(pid)
                if det:
                    if not lead["website"]:
                        lead["website"] = det.get("websiteUri") or ""
                    if not lead["phone"]:
                        lead["phone"] = det.get("internationalPhoneNumber") or ""

        # пишем в ClickUp (там уже есть защита от лимита cf)
        clickup_client.upsert_lead(list_id, lead)
        created += 1

    total_in_list = len(clickup_client.get_leads_from_list(list_id))

    return {
        "state": state,
        "found": len(raw_places),
        "created": created,
        "skipped": skipped,
        "total_in_list": total_in_list,
    }
