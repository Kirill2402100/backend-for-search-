# leads.py
import logging
from typing import Dict, Any, List

from google_places import GooglePlacesClient
from clickup_client import clickup_client

log = logging.getLogger("leads")


def _queries_for_state(state: str) -> List[str]:
    # то, что у тебя было — только в одном месте
    return [
        f"dentist {state}",
        f"dental clinic {state}",
        f"cosmetic dentist {state}",
        f"orthodontist {state}",
        f"family dentist {state}",
        f"pediatric dentist {state}",
        f"oral surgery {state}",
    ]


def upsert_leads_for_state(state: str) -> Dict[str, int]:
    client = GooglePlacesClient()

    queries = _queries_for_state(state)
    log.info("leads:google (new) queries for %s -> %d queries", state, len(queries))

    raw_places: List[Dict[str, Any]] = []
    for q in queries:
        places = client.search_places(q)
        log.info("leads:google (new) '%s' -> %d places", q, len(places))
        raw_places.extend(places)

    # дедуп по place_id
    seen = set()
    unique: List[Dict[str, Any]] = []
    for p in raw_places:
        pid = p.get("place_id")
        if not pid:
            # иногда можно по названию
            pid = f"{p.get('name','').lower()}::{p.get('formatted_address','').lower()}"
        if pid in seen:
            continue
        seen.add(pid)
        unique.append(p)

    log.info("leads:after dedupe -> %d places for %s", len(unique), state)

    list_id = clickup_client.get_or_create_list_for_state(state)

    created = 0
    skipped = 0
    for p in unique:
        lead = {
            # ВОТ: берём нормальное имя
            "name": p.get("name") or "Clinic",
            "website": p.get("website"),
            "email": p.get("email"),
            "facebook": p.get("facebook"),
            "instagram": p.get("instagram"),
            "linkedin": p.get("linkedin"),
            "address": p.get("formatted_address"),
            "source": "google",
        }
        try:
            clickup_client.upsert_lead(list_id, lead)
            created += 1
        except Exception as e:
            log.warning("leads: cannot create lead %s: %s", lead.get("name"), e)
            skipped += 1

    return {
        "found": len(unique),
        "created": created,
        "skipped": skipped,
    }
