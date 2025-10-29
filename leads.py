# leads.py
"""
Собираем лидов по штату из Google Places и добавляем в ClickUp.
Нужны переменные окружения:
  - GOOGLE_PLACES_API_KEY
Опционально:
  - MAX_LEADS_PER_STATE (по умолчанию 80)
"""

from __future__ import annotations
import os
import time
import requests
from typing import Dict, List, Iterable, Tuple

from clickup_client import clickup_client, READY_STATUS, NEW_STATUS  # NEW_STATUS есть в client
from config import settings

GOOGLE_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
MAX_LEADS = int(os.getenv("MAX_LEADS_PER_STATE", "80"))

# маппинг штатов: аббревиатура -> полное имя (для запросов)
US_STATE_NAMES: Dict[str, str] = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado","CT":"Connecticut",
    "DE":"Delaware","FL":"Florida","GA":"Georgia","HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa",
    "KS":"Kansas","KY":"Kentucky","LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan",
    "MN":"Minnesota","MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire",
    "NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota","OH":"Ohio","OK":"Oklahoma",
    "OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina","SD":"South Dakota","TN":"Tennessee",
    "TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia","WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming"
}

# несколько крупных городов для ряда штатов (для лучшей выборки);
# если штата нет в списке — упадём на общий поиск "Dentist in <StateName>"
TOP_CITIES: Dict[str, List[str]] = {
    "NY": ["New York", "Brooklyn", "Queens", "Bronx", "Staten Island", "Buffalo", "Rochester", "Yonkers", "Syracuse", "Albany"],
    "CA": ["Los Angeles", "San Diego", "San Jose", "San Francisco", "Fresno", "Sacramento", "Long Beach", "Oakland", "Bakersfield"],
    "FL": ["Miami", "Orlando", "Tampa", "Jacksonville", "St. Petersburg", "Hialeah"],
    "TX": ["Houston", "Dallas", "San Antonio", "Austin", "Fort Worth", "El Paso"],
}

PLACES_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def _g_places_text_search(query: str, key: str, pages: int = 3) -> Iterable[Dict]:
    """Итератор результатов Text Search (с пейджингом)."""
    next_page = None
    for _ in range(pages):
        params = {"query": query, "type": "dentist", "key": key}
        if next_page:
            params["pagetoken"] = next_page
            # per Google требуются ~2 сек перед использованием next_page_token
            time.sleep(2.0)
        r = requests.get(PLACES_SEARCH_URL, params=params, timeout=30)
        data = r.json()
        for item in data.get("results", []):
            yield item
        next_page = data.get("next_page_token")
        if not next_page:
            break


def _g_place_details(place_id: str, key: str) -> Dict:
    params = {
        "place_id": place_id,
        "fields": "name,formatted_address,formatted_phone_number,website,place_id",
        "key": key,
    }
    r = requests.get(PLACES_DETAILS_URL, params=params, timeout=30)
    return r.json().get("result", {}) or {}


def _dedup(leads: Iterable[Dict]) -> List[Dict]:
    """Дедуп по website -> phone -> name+address."""
    out: List[Dict] = []
    seen_web: set = set()
    seen_phone: set = set()
    seen_sig: set = set()
    for l in leads:
        web = (l.get("website") or "").strip().lower()
        ph = (l.get("phone") or "").strip()
        sig = (l.get("name","").strip().lower(), l.get("address","").strip().lower())
        if web and web in seen_web:
            continue
        if (not web) and ph and ph in seen_phone:
            continue
        if (not web) and (not ph) and sig in seen_sig:
            continue
        if web: seen_web.add(web)
        elif ph: seen_phone.add(ph)
        else: seen_sig.add(sig)
        out.append(l)
    return out


def collect_from_google(state_code: str) -> List[Dict]:
    """Собираем из Google Places. Возвращаем список словарей лидов."""
    if not GOOGLE_KEY:
        return []

    state_name = US_STATE_NAMES.get(state_code.upper(), state_code.upper())
    queries: List[str] = []
    cities = TOP_CITIES.get(state_code.upper())
    if cities:
        for c in cities:
            queries.append(f"Dentist in {c}, {state_code}")
    else:
        queries.append(f"Dentist in {state_name}")

    leads: List[Dict] = []
    for q in queries:
        # до 3 страниц по каждому запросу (примерно до ~60 мест)
        for item in _g_places_text_search(q, GOOGLE_KEY, pages=3):
            pid = item.get("place_id")
            if not pid:
                continue
            details = _g_place_details(pid, GOOGLE_KEY)
            name = details.get("name") or item.get("name")
            if not name:
                continue
            leads.append({
                "name": name,
                "address": details.get("formatted_address") or item.get("formatted_address"),
                "phone": details.get("formatted_phone_number"),
                "website": details.get("website"),
                "source": f"GooglePlaces:{pid}",
            })
            if len(leads) >= MAX_LEADS:
                break
        if len(leads) >= MAX_LEADS:
            break

    return _dedup(leads)


def _existing_keys_for_list(list_id: str) -> Tuple[set, set, set]:
    """Собираем ключи существующих лидов, чтобы не плодить дубликаты."""
    tasks = clickup_client.get_leads_from_list(list_id)
    by_web, by_phone, by_sig = set(), set(), set()
    for t in tasks:
        web = (t.get("website") or "").strip().lower()
        ph = (t.get("phone") or "").strip()
        sig = (t.get("clinic_name","").strip().lower(), t.get("address","").strip().lower())
        if web: by_web.add(web)
        if ph: by_phone.add(ph)
        by_sig.add(sig)
    return by_web, by_phone, by_sig


def _create_task_in_clickup(list_id: str, lead: Dict) -> None:
    """
    Создаём задачу. Используем клиентские заголовки/базовый URL из clickup_client.
    Пишем в описание телефоны/сайт/источник.
    """
    desc_lines = []
    if lead.get("website"): desc_lines.append(f"Website: {lead['website']}")
    if lead.get("phone"): desc_lines.append(f"Phone: {lead['phone']}")
    if lead.get("address"): desc_lines.append(f"Address: {lead['address']}")
    if lead.get("source"): desc_lines.append(f"Source: {lead['source']}")
    description = "\n".join(desc_lines) or "—"

    payload = {
        "name": lead["name"],
        "description": description,
        "status": NEW_STATUS,  # кладём в NEW, ты сам потом помечаешь READY
    }
    url = f"{clickup_client.BASE_URL}/list/{list_id}/task"
    r = requests.post(url, headers=clickup_client.headers, json=payload, timeout=30)
    r.raise_for_status()


def upsert_leads_for_state(state_code: str) -> Dict[str, int]:
    """
    Главная функция: создаёт/находит лист, собирает лидов и добавляет новые.
    Возвращает отчёт по количествам.
    """
    list_id = clickup_client.get_or_create_list_for_state(state_code)
    # статусы уже обеспечиваются клиентом, оставляем как есть

    # собираем
    g_leads = collect_from_google(state_code)

    # дедуп по существующим
    by_web, by_phone, by_sig = _existing_keys_for_list(list_id)
    created, skipped = 0, 0
    for lead in g_leads:
        web = (lead.get("website") or "").strip().lower()
        ph = (lead.get("phone") or "").strip()
        sig = (lead.get("name","").strip().lower(), (lead.get("address") or "").strip().lower())
        if (web and web in by_web) or (not web and ph and ph in by_phone) or (not web and not ph and sig in by_sig):
            skipped += 1
            continue
        try:
            _create_task_in_clickup(list_id, lead)
            created += 1
            if web: by_web.add(web)
            elif ph: by_phone.add(ph)
            else: by_sig.add(sig)
        except Exception:
            # проглатываем единичные ошибки, чтобы не падать всю загрузку
            skipped += 1

    return {
        "collected": len(g_leads),
        "created": created,
        "skipped": skipped,
        "list_id": list_id,
    }
