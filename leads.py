# leads.py
import logging
from typing import Dict, Any, List, Set, Tuple

from google_places import GooglePlacesClient
from clickup_client import clickup_client

log = logging.getLogger("leads")

_gp = GooglePlacesClient()


def _queries_for_state(state: str) -> List[str]:
    state = state.upper()

    # Нью-Йорк — тот самый случай, когда у нас было 123
    if state == "NY":
        return [
            "dentist NY",
            "dental clinic NY",
            "dentist Manhattan NY",
            "dentist Brooklyn NY",
            "dentist Queens NY",
            "dentist Bronx NY",
            "dentist Staten Island NY",
        ]

    # Флорида — тот самый случай с ~187
    if state == "FL":
        return [
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
        ]

    # дефолт для остальных штатов
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
    """
    Главная функция, которую вызывает телеграм-бот.
    Возвращаем счётчики, чтобы бот написал в чат.
    """
    list_id = clickup_client.get_or_create_list_for_state(state)
    queries = _queries_for_state(state)
    log.info("leads:google (new) queries for %s -> %d queries", state, len(queries))

    raw_places: List[Dict[str, Any]] = []
    for q in queries:
        places = _gp.search(q)
        log.info("leads:google (new) %r -> %d places", q, len(places))
        raw_places.extend(places)

    # дедуп
    seen: Set[Tuple[str, str]] = set()
    unique_places: List[Dict[str, Any]] = []
    for p in raw_places:
        key = (p.get("place_id") or "", (p.get("name") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        unique_places.append(p)

    log.info("leads:after dedupe -> %d places for %s", len(unique_places), state)

    created = 0
    skipped = 0

    for p in unique_places:
        try:
            lead = {
                "name": p.get("name") or "Clinic",
                "address": p.get("address") or "",
                "website": p.get("website") or "",
                "facebook": p.get("facebook") or "",
                "instagram": p.get("instagram") or "",
                "linkedin": p.get("linkedin") or "",
                "source": p.get("source") or "google",
                "status": "NEW",
            }
            clickup_client.upsert_lead(list_id, lead)
            created += 1
        except Exception as e:
            log.warning("leads: cannot upsert %s: %s", p.get("name"), e)
            skipped += 1

    return {
        "found": len(unique_places),
        "created": created,
        "skipped": skipped,
    }
