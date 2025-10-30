# leads.py
import logging
import os
from typing import Dict, Any, List, Tuple

import requests

from config import settings
from clickup_client import clickup_client

log = logging.getLogger("leads")

GOOGLE_PLACES_API_KEY = getattr(settings, "GOOGLE_PLACES_API_KEY", "") or os.getenv("GOOGLE_PLACES_API_KEY", "")

# можно расширять
GOOGLE_QUERIES = [
    "dentist in {state}",
    "dental clinic in {state}",
    "orthodontist in {state}",
    "periodontist in {state}",
    "pediatric dentist in {state}",
]


def _google_places_new_search_all(text: str) -> List[Dict[str, Any]]:
    """
    Тянем ВСЕ страницы, пока Google отдаёт nextPageToken.
    У Google всё равно есть лимиты по проекту/суткам, поэтому «бесконечно» он не даст.
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
            "places.nationalPhoneNumber,places.websiteUri"
        ),
    }

    out: List[Dict[str, Any]] = []
    page_token = None
    page_no = 0
    MAX_PAGES = 50  # страховка, но это уже тысячи мест

    while True:
        body: Dict[str, Any] = {"textQuery": text}
        if page_token:
            body["pageToken"] = page_token

        resp = requests.post(url, headers=headers, json=body, timeout=20)
        data = resp.json()
        if resp.status_code != 200:
            log.warning("google textsearch status=%s data=%s", resp.status_code, data)
            break

        places = data.get("places", [])
        out.extend(places)

        page_token = data.get("nextPageToken")
        page_no += 1
        if not page_token:
            break
        if page_no >= MAX_PAGES:
            break

    return out


def _collect_from_google(state: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    for q in GOOGLE_QUERIES:
        text = q.format(state=state)
        places = _google_places_new_search_all(text)
        for p in places:
            lead = {
                "name": p.get("displayName", {}).get("text") or "",
                "address": p.get("formattedAddress") or "",
                "phone": p.get("nationalPhoneNumber") or "",
                "website": p.get("websiteUri") or "",
                "email": "",  # гугл не даёт
                "source": "google-places-new",
                "place_id": p.get("id") or "",
            }
            found.append(lead)

    # де-дуп по (name, address)
    dedup: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for l in found:
        key = (l["name"].lower(), l["address"].lower())
        if key not in dedup:
            dedup[key] = l
    result = list(dedup.values())
    log.info("google (new) collected %d unique places for %s", len(result), state)
    return result


def upsert_leads_for_state(state: str) -> Dict[str, Any]:
    list_id = clickup_client.get_or_create_list_for_state(state)
    log.info("start collecting for %s -> list %s", state, list_id)

    leads: List[Dict[str, Any]] = []
    leads.extend(_collect_from_google(state))

    created = 0
    skipped = 0
    for lead in leads:
        try:
            clickup_client.upsert_lead(list_id, lead)
            created += 1
        except Exception as e:
            log.error("cannot create lead %s: %s", lead.get("name"), e)
            skipped += 1

    return {
        "state": state,
        "list_id": list_id,
        "found": len(leads),
        "created": created,
        "skipped": skipped,
    }
