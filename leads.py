# leads.py
import os
import logging
from typing import Dict, Any, List

import requests

from clickup_client import clickup_client

log = logging.getLogger("leads")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
EMAIL_VALIDATION_API_KEY = os.getenv("EMAIL_VALIDATION_API_KEY", "")
EMAIL_VALIDATION_PROVIDER = os.getenv("EMAIL_VALIDATION_PROVIDER", "")

# мы специально НЕ даём лимит страниц — берём столько, сколько собрали из запросов
GOOGLE_PLACES_BASE = "https://places.googleapis.com/v1/places:searchText"

# базовый набор запросов по штату
STATE_QUERIES = {
    # штат: список поисков
    # для FL я специально добавил больше городов
    "NY": [
        "dentist NY",
        "dental clinic NY",
        "dentist Manhattan NY",
        "dentist Brooklyn NY",
        "dentist Queens NY",
        "dentist Bronx NY",
        "dentist Staten Island NY",
    ],
    "FL": [
        "dentist FL",
        "dental clinic FL",
        "cosmetic dentist FL",
        "orthodontist FL",
        "dentist Miami FL",
        "dentist Orlando FL",
        "dentist Tampa FL",
        "dentist Jacksonville FL",
        "dentist Fort Lauderdale FL",
        "dentist West Palm Beach FL",
    ],
}


def _google_search_one(query: str) -> List[Dict[str, Any]]:
    if not GOOGLE_PLACES_API_KEY:
        log.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return []

    headers = {
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": (
            "places.displayName,places.formattedAddress,places.websiteUri,"
            "places.internationalPhoneNumber,places.googleMapsUri,"
            "places.primaryType,places.id"
        ),
    }
    payload = {"textQuery": query}
    r = requests.post(GOOGLE_PLACES_BASE, headers=headers, json=payload, timeout=15)
    if r.status_code >= 400:
        log.warning("google textsearch %s -> %s %s", query, r.status_code, r.text[:200])
        return []
    data = r.json()
    places = data.get("places") or []
    log.info("leads:google (new) '%s' -> %d places", query, len(places))
    return places


def _places_for_state(state: str) -> List[Dict[str, Any]]:
    qs = STATE_QUERIES.get(state.upper())
    if not qs:
        # дефолт — просто штат
        qs = [f"dentist {state}"]
    all_places: List[Dict[str, Any]] = []
    for q in qs:
        all_places.extend(_google_search_one(q))
    # дедуп по place_id / displayName+address
    uniq: Dict[str, Dict[str, Any]] = {}
    for p in all_places:
        pid = p.get("id") or p.get("name") or p.get("googleMapsUri") or p.get("displayName", {}).get("text")
        if not pid:
            continue
        uniq[pid] = p
    out = list(uniq.values())
    log.info("leads:after dedupe -> %d places for %s", len(out), state)
    return out


def _lead_from_place(p: Dict[str, Any]) -> Dict[str, Any]:
    name = (p.get("displayName") or {}).get("text") or "No name"
    website = p.get("websiteUri") or ""
    phone = p.get("internationalPhoneNumber") or ""
    # соцсети редко есть в Places, оставляем пустыми
    return {
        "name": name,
        "website": website,
        "email": "",      # будешь дальше обогащать
        "facebook": "",
        "instagram": "",
        "linkedin": "",
        "phone": phone,
    }


def upsert_leads_for_state(state: str) -> Dict[str, int]:
    list_id = clickup_client.get_or_create_list_for_state(state)
    places = _places_for_state(state)

    found = len(places)
    created = 0
    skipped = 0

    for p in places:
        lead = _lead_from_place(p)
        try:
            ok = clickup_client.upsert_lead(list_id, lead)
            if ok:
                created += 1
            else:
                skipped += 1
        except Exception as e:
            # важно не падать из-за одной плохой задачи
            skipped += 1
            log.warning("cannot upsert lead %s: %s", lead.get("name"), e)

    return {
        "found": found,
        "created": created,
        "skipped": skipped,
    }
