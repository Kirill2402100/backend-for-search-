# google_places.py
import os
import time
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("google_places")

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


class GooglePlacesClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or API_KEY
        if not self.api_key:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is not set")
        self.session = requests.Session()

    # ─────────────────────────────
    # ВАЖНО: leads.py зовёт client.search(...)
    # мы держим этот метод и просто прокидываем в search_text
    # ─────────────────────────────
    def search(self, query: str) -> List[Dict[str, Any]]:
        return self.search_text(query)

    def search_text(self, query: str) -> List[Dict[str, Any]]:
        """
        Собираем все страницы textsearch для одного запроса.
        Google может отдавать next_page_token — перелистываем пока есть.
        """
        all_res: List[Dict[str, Any]] = []
        params = {"query": query, "key": self.api_key}
        next_token: Optional[str] = None

        while True:
            if next_token:
                params = {"pagetoken": next_token, "key": self.api_key}

            r = self.session.get(TEXTSEARCH_URL, params=params, timeout=20)
            data = r.json()
            status = data.get("status")

            if status not in ("OK", "ZERO_RESULTS"):
                # это мы уже видели: REQUEST_DENIED, если legacy и т.п.
                log.warning("google textsearch status=%s data=%s", status, data)
                break

            results = data.get("results", [])
            all_res.extend(results)

            next_token = data.get("next_page_token")
            if not next_token:
                break

            # токен активируется не сразу
            time.sleep(2.0)

        log.info("google (new) '%s' -> %d places", query, len(all_res))
        return all_res

    def get_details(self, place_id: str) -> Dict[str, Any]:
        """
        Детали по месту — пробуем вытащить сайт/телефон/адрес.
        """
        params = {
            "place_id": place_id,
            "key": self.api_key,
            "fields": "name,formatted_address,formatted_phone_number,website,url",
        }
        r = self.session.get(DETAILS_URL, params=params, timeout=20)
        data = r.json()
        if data.get("status") != "OK":
            return {}
        return data.get("result", {})
