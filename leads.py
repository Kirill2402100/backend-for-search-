# leads.py
import logging
from typing import List, Dict, Any, Set

import requests

from config import settings
from clickup_client import clickup_client

log = logging.getLogger("leads")

# базовые запросы для любого штата
BASE_QUERIES = [
    "dentist {state}",
    "dental clinic {state}",
    "cosmetic dentist {state}",
    "orthodontist {state}",
]

# дополнительные города/регионы по штатам
STATE_CITY_QUERIES: Dict[str, List[str]] = {
    # Нью-Йорк — тут и правда есть боро
    "NY": [
        "dentist Manhattan NY",
        "dentist Brooklyn NY",
        "dentist Queens NY",
        "dentist Bronx NY",
        "dentist Staten Island NY",
    ],
    # Флорида — добавим крупные города
    "FL": [
        "dentist Miami FL",
        "dentist Orlando FL",
        "dentist Tampa FL",
        "dentist Jacksonville FL",
        "dentist Fort Lauderdale FL",
        "dentist West Palm Beach FL",
    ],
    # Калифорния — на будущее
    "CA": [
        "dentist Los Angeles CA",
        "dentist San Francisco CA",
        "dentist San Diego CA",
        "dentist Sacramento CA",
    ],
}

# что хотим хранить (пока будем заполнять только website)
SOCIAL_FIELDS = ["facebook", "instagram", "linkedin"]


def _places_search_text(api_key: str, text_query: str):
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,"
            "places.displayName.text,"
            "places.formattedAddress,"
            "places.websiteUri,"
            "places.googleMapsUri"
        ),
    }
    body = {
        "textQuery": text_query,
        "pageSize": 20,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=15)
    if resp.status_code != 200:
        log.warning("google textsearch status=%s data=%s", resp.status_code, resp.text)
        return [], None
    data = resp.json()
    return data.get("places", []), data.get("nextPageToken")


def _collect_all_pages(api_key: str, query: str) -> List[Dict[str, Any]]:
    all_places: List[Dict[str, Any]] = []

    places, next_token = _places_search_text(api_key, query)
    all_places.extend(places)

    # крутимся пока дают токен
    while next_token:
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,"
                "places.displayName.text,"
                "places.formattedAddress,"
                "places.websiteUri,"
                "places.googleMapsUri"
            ),
        }
        body = {
            "textQuery": query,
            "pageSize": 20,
            "pageToken": next_token,
        }
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        if resp.status_code != 200:
            log.warning(
                "google textsearch page status=%s data=%s", resp.status_code, resp.text
            )
            break
        data = resp.json()
        places = data.get("places", [])
        all_places.extend(places)
        next_token = data.get("nextPageToken")

    return all_places


def _normalize_place(p: Dict[str, Any]) -> Dict[str, Any]:
    name = (p.get("displayName") or {}).get("text") or ""
    website = p.get("websiteUri") or ""
    address = p.get("formattedAddress") or ""
    gmaps = p.get("googleMapsUri") or ""

    out = {
        "place_id": p.get("id") or "",
        "name": name,
        "website": website,
        "address": address,
        "google_maps": gmaps,
    }
    # заготовим соцсети, но пока пустые — из Places их нет
    for sf in SOCIAL_FIELDS:
        out[sf] = ""
    return out


def upsert_leads_for_state(state: str) -> Dict[str, int]:
    state = state.upper()

    api_key = getattr(settings, "GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        log.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return {"found": 0, "created": 0, "skipped": 0}

    # получаем список
    list_id = clickup_client.get_or_create_list_for_state(state)
    log.info("start collecting for %s -> list %s", state, list_id)

    # какие запросы будем делать именно для этого штата
    queries: List[str] = [q.format(state=state) for q in BASE_QUERIES]
    extra = STATE_CITY_QUERIES.get(state, [])
    if extra:
        queries.extend(extra)

    seen: Set[str] = set()
    leads: List[Dict[str, Any]] = []

    for q in queries:
        places = _collect_all_pages(api_key, q)
        log.info("google (new) '%s' -> %d places", q, len(places))
        for p in places:
            pid = p.get("id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            leads.append(_normalize_place(p))

    log.info("leads:after dedupe -> %d places for %s", len(leads), state)

    found = len(leads)
    created = 0
    skipped = 0

    for lead in leads:
        ok = clickup_client.upsert_lead(list_id, lead)
        if ok:
            created += 1
        else:
            skipped += 1

    return {"found": found, "created": created, "skipped": skipped}
