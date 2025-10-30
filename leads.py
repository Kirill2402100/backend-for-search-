# leads.py
import logging
import os
from typing import Any, Dict, List, Tuple

import requests

from clickup_client import clickup_client

log = logging.getLogger("leads")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

# какие запросы для штата делать
# пока примитивно — один текстовый запрос вида "dentist new york"
STATE_QUERY_TEMPLATE = "dentist {state}"


def _google_places_textsearch_all(query: str) -> List[Dict[str, Any]]:
    """
    Забираем ВСЕ страницы из Places API (New).
    Раз ты сказал «не ограничиваться потолком» — крутим next_page_token.
    """
    if not GOOGLE_PLACES_API_KEY:
        log.warning("GOOGLE_PLACES_API_KEY is empty -> google search skipped")
        return []

    # НОВЫЙ endpoint
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
    page_token: str = ""

    while True:
        body: Dict[str, Any] = {
            "textQuery": query,
        }
        if page_token:
            body["pageToken"] = page_token

        resp = requests.post(url, json=body, headers=headers, timeout=20)
        data = resp.json()

        if resp.status_code != 200:
            log.warning("google textsearch status=%s data=%s", resp.status_code, data)
            break

        places = data.get("places", [])
        all_places.extend(places)

        page_token = data.get("nextPageToken") or ""
        if not page_token:
            break

    log.info("google (new) returned %d places for %s", len(all_places), query)
    return all_places


def _normalize_place(p: Dict[str, Any]) -> Dict[str, Any]:
    """Приводим гугловскую карточку к нашему виду."""
    return {
        "name": (p.get("displayName") or {}).get("text") or "No name",
        "address": p.get("formattedAddress") or "",
        "phone": p.get("internationalPhoneNumber") or "",
        "website": p.get("websiteUri") or "",
        # email отсюда не достанем — будет пусто
        "email": "",
        "notes": "",
    }


def _existing_keys_for_list(list_id: str) -> Tuple[set, set, set]:
    """
    Чтобы не создавать дубликаты.
    Вернём 3 множества:
      - по имени
      - по телефону
      - по сайту
    """
    tasks = clickup_client.get_leads_from_list(list_id)
    by_name = {t["name"].strip().lower() for t in tasks if t.get("name")}
    by_phone = {str(t.get("phone") or "").strip() for t in tasks if t.get("phone")}
    by_site = {str(t.get("website") or "").strip().lower() for t in tasks if t.get("website")}
    return by_name, by_phone, by_site


def upsert_leads_for_state(state: str) -> Dict[str, Any]:
    """
    Главная функция, которую зовёт телеграм-бот.
    """
    list_id = clickup_client.get_or_create_list_for_state(state)
    log.info("start collecting for %s -> list %s", state, list_id)

    # 1. заберём уже существующее, чтобы отфильтровать
    by_name, by_phone, by_site = _existing_keys_for_list(list_id)

    # 2. пойдём в гугл
    query = STATE_QUERY_TEMPLATE.format(state=state)
    places = _google_places_textsearch_all(query)

    created = 0
    skipped = 0

    for p in places:
        lead = _normalize_place(p)

        key_name = lead["name"].strip().lower()
        key_phone = lead["phone"].strip()
        key_site = lead["website"].strip().lower()

        if (
            key_name in by_name
            or (key_phone and key_phone in by_phone)
            or (key_site and key_site in by_site)
        ):
            skipped += 1
            continue

        # создаём задачу в ClickUp → всегда в NEW (это внутри клиента)
        clickup_client.upsert_lead(list_id, lead)

        # и запоминаем, чтобы в этом же прогоне не создать ещё раз
        by_name.add(key_name)
        if key_phone:
            by_phone.add(key_phone)
        if key_site:
            by_site.add(key_site)

        created += 1

    # Сразу после импорта можно получить свежую статистику по листу
    tasks_after = clickup_client.get_leads_from_list(list_id)
    total = len(tasks_after)
    with_email = sum(1 for t in tasks_after if t.get("email"))
    without_email = total - with_email
    ready = sum(1 for t in tasks_after if t.get("status") == "READY")
    sent = sum(1 for t in tasks_after if t.get("status") == "SENT")
    remain = sum(1 for t in tasks_after if t.get("status") not in ("SENT",))

    return {
        "list_id": list_id,
        "found": len(places),
        "created": created,
        "skipped": skipped,
        "stats": {
            "total": total,
            "with_email": with_email,
            "without_email": without_email,
            "ready": ready,
            "sent": sent,
            "remaining": remain,
        },
    }
