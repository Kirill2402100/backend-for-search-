# leads.py
from typing import List, Dict, Any
import os
import logging

from google_places import GooglePlacesClient
from clickup_client import clickup_client

log = logging.getLogger("leads")

# если хочешь – можешь потом вынести в отдельный файл
STATE_CITIES: Dict[str, List[str]] = {
    "NY": ["New York", "Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island", "Long Island"],
    "FL": ["Miami", "Orlando", "Tampa", "Jacksonville", "Fort Lauderdale", "West Palm Beach", "Tallahassee"],
    "CA": ["Los Angeles", "San Francisco", "San Diego", "Sacramento", "San Jose", "Fresno", "Oakland"],
    "TX": ["Houston", "Dallas", "Austin", "San Antonio", "Fort Worth", "El Paso"],
    "IL": ["Chicago", "Aurora", "Naperville"],
    "GA": ["Atlanta", "Savannah", "Augusta"],
    # остальные штаты получат «общий» набор
}

# базовые фразы, которые мы комбинируем
BASE_QUERIES = [
    "dentist {state}",
    "dental clinic {state}",
    "cosmetic dentist {state}",
    "orthodontist {state}",
]

# что подставляем в конце для городов
CITY_QUERIES = [
    "dentist {city} {state}",
    "dental clinic {city} {state}",
]

# если вдруг кто-то опять поставит лимит в env – уважаем, но не требуем
MAX_PLACES_ENV = os.getenv("GOOGLE_PLACES_MAX_PAGES")


def _build_queries_for_state(state: str) -> List[str]:
    state = state.upper()
    queries: List[str] = []

    # 1) общие по штату
    for tpl in BASE_QUERIES:
        queries.append(tpl.format(state=state))

    # 2) по городам, если мы их знаем
    cities = STATE_CITIES.get(state)
    if cities:
        for city in cities:
            for tpl in CITY_QUERIES:
                queries.append(tpl.format(city=city, state=state))
    else:
        # если городов нет – всё равно не отдаёмся на милость Google одной выдачей
        extra = [
            f"family dentist {state}",
            f"pediatric dentist {state}",
            f"oral surgery {state}",
        ]
        queries.extend(extra)

    return queries


def upsert_leads_for_state(state: str) -> Dict[str, int]:
    """
    1. Строим пачку поисков.
    2. Тащим по каждому запросу из нового Places.
    3. Дедупим по place_id / названию.
    4. Пихаем в ClickUp.
    """
    state = state.upper()
    client = GooglePlacesClient()

    all_places: Dict[str, Dict[str, Any]] = {}  # key -> place dict

    queries = _build_queries_for_state(state)
    log.info("leads:google (new) queries for %s -> %d queries", state, len(queries))

    for q in queries:
        places = client.search(q)
        log.info("leads:google (new) '%s' -> %d places", q, len(places))
        for p in places:
            # ключ – либо place_id, либо name+addr
            pid = p.get("place_id") or f"{p.get('name','').lower()}::{p.get('formatted_address','').lower()}"
            if pid not in all_places:
                all_places[pid] = p

    # теперь у нас есть все уникальные
    places_list = list(all_places.values())
    log.info("leads:after dedupe -> %d places for %s", len(places_list), state)

    list_id = clickup_client.get_or_create_list_for_state(state)

    created = 0
    skipped = 0
    for pl in places_list:
        lead = {
            "clinic_name": pl.get("name") or "",
            "address": pl.get("formatted_address") or "",
            # пока у нас нет откуда взять email / соцсети из Google Places (туда их просто не отдают)
            # поэтому кладём пустые – но поля в ClickUp мы уже создаём
            "email": "",
            "website": pl.get("website") or "",
            "facebook": "",
            "instagram": "",
            "linkedin": "",
        }
        ok = clickup_client.upsert_lead(list_id, lead)
        if ok:
            created += 1
        else:
            skipped += 1

    return {
        "found": len(places_list),
        "created": created,
        "skipped": skipped,
    }
