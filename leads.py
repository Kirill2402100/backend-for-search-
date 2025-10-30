# leads.py
import os
import logging
from typing import Dict, Any, List, Optional, Tuple
import requests

from clickup_client import clickup_client

log = logging.getLogger("leads")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

# базовые запросы для любого штата
BASE_QUERIES = [
    "dentist {state}",
    "dental clinic {state}",
]

# доп.запросы специально для NY (иначе гугл очень быстро «заканчивается»)
NY_EXTRA_QUERIES = [
    "dentist Manhattan NY",
    "dentist Brooklyn NY",
    "dentist Queens NY",
    "dentist Bronx NY",
    "dentist Staten Island NY",
]


def _google_search_text(text_query: str) -> List[Dict[str, Any]]:
    """
    Один вызов searchText с прокруткой всех страниц, пока google даёт nextPageToken.
    """
    if not GOOGLE_PLACES_API_KEY:
        log.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return []

    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.websiteUri,places.internationalPhoneNumber"
        ),
    }

    all_places: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    page_num = 0

    while True:
        body: Dict[str, Any] = {"textQuery": text_query}
        if page_token:
            body["pageToken"] = page_token

        resp = requests.post(url, headers=headers, json=body, timeout=30)
        data = resp.json()
        if resp.status_code != 200:
            log.warning("google textsearch '%s' status=%s data=%s", text_query, resp.status_code, data)
            break

        places = data.get("places", [])
        all_places.extend(places)

        page_num += 1
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    log.info("google (new) '%s' -> %s places", text_query, len(all_places))
    return all_places


def _google_place_details(place_id: str) -> Dict[str, Any]:
    if not GOOGLE_PLACES_API_KEY:
        return {}
    fields = "id,displayName,formattedAddress,websiteUri,internationalPhoneNumber"
    url = f"https://places.googleapis.com/v1/{place_id}"
    params = {"key": GOOGLE_PLACES_API_KEY, "fields": fields}
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        log.warning("google details %s -> %s %s", place_id, r.status_code, r.text[:200])
        return {}
    return r.json()


def _normalize_place(place: Dict[str, Any]) -> Dict[str, Any]:
    name = (place.get("displayName") or {}).get("text") or place.get("name") or "Unknown"
    addr = place.get("formattedAddress") or ""
    website = place.get("websiteUri") or ""
    phone = place.get("internationalPhoneNumber") or ""

    return {
        "name": name,
        "address": addr,
        "email": "",
        "website": website,
        "facebook": "",
        "instagram": "",
        "linkedin": "",
        "phone": phone,
    }


def _dedupe_places(places: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Дедуп по (name, address) — этого обычно достаточно.
    """
    seen: set[Tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []
    for p in places:
        name = (p.get("displayName") or {}).get("text") or p.get("name") or ""
        addr = p.get("formattedAddress") or ""
        key = (name.lower().strip(), addr.lower().strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def upsert_leads_for_state(state: str) -> Dict[str, Any]:
    list_id = clickup_client.get_or_create_list_for_state(state)
    log.info("start collecting for %s -> list %s", state, list_id)

    # 1. соберём список запросов
    queries = [q.format(state=state) for q in BASE_QUERIES]
    if state.upper() == "NY":
        queries += NY_EXTRA_QUERIES

    # 2. собираем всё по всем запросам
    raw_all: List[Dict[str, Any]] = []
    for q in queries:
        raw_all.extend(_google_search_text(q))

    # 3. дедуп
    raw_all = _dedupe_places(raw_all)
    log.info("after dedupe -> %s places for %s", len(raw_all), state)

    created = 0
    skipped = 0

    for place in raw_all:
        lead = _normalize_place(place)

        # если сайта/телефона нет — дотянем
        if (not lead["website"]) or (not lead["phone"]):
            pid = place.get("id")
            if pid:
                det = _google_place_details(pid)
                if det:
                    if not lead["website"]:
                        lead["website"] = det.get("websiteUri") or ""
                    if not lead["phone"]:
                        lead["phone"] = det.get("internationalPhoneNumber") or ""

        clickup_client.upsert_lead(list_id, lead)
        created += 1

    total_in_list = len(clickup_client.get_leads_from_list(list_id))

    return {
        "state": state,
        "found": len(raw_all),
        "created": created,
        "skipped": skipped,
        "total_in_list": total_in_list,
    }
