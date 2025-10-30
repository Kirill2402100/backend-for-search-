# google_places.py
import os
import time
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("google_places")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


class GooglePlacesClient:
    """
    Минимальный клиент под наш сценарий:
    - text search с автопагинацией
    - details по place_id (на будущее)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or GOOGLE_PLACES_API_KEY
        if not self.api_key:
            # лучше уронить сервис при старте, чем молча ничего не собирать
            raise RuntimeError("GOOGLE_PLACES_API_KEY is not set")

        self.session = requests.Session()

    # -------- public --------

    def search_text(self, query: str) -> List[Dict[str, Any]]:
        """
        Делает text search и САМ проходит все страницы,
        пока Google отдаёт next_page_token.
        Возвращает список place-объектов (как в ответе Google).
        """
        all_results: List[Dict[str, Any]] = []

        params = {
            "query": query,
            "key": self.api_key,
        }

        next_token: Optional[str] = None

        while True:
            if next_token:
                params = {
                    "pagetoken": next_token,
                    "key": self.api_key,
                }

            resp = self.session.get(TEXT_SEARCH_URL, params=params, timeout=20)
            data = resp.json()

            status = data.get("status")
            if status not in ("OK", "ZERO_RESULTS"):
                # если что-то пошло не так — выходим с тем, что есть
                log.warning("google_places: search '%s' -> status %s", query, status)
                break

            results = data.get("results", [])
            all_results.extend(results)

            next_token = data.get("next_page_token")
            if not next_token:
                break

            # у Google next_page_token активируется не сразу
            time.sleep(2.0)

        log.info("google (new) '%s' -> %d places", query, len(all_results))
        return all_results

    def get_details(self, place_id: str) -> Dict[str, Any]:
        """
        Если когда-то понадобится добрать телефон/сайт.
        Сейчас leads.py может это не вызывать — просто держим тут.
        """
        params = {
            "place_id": place_id,
            "key": self.api_key,
            "fields": "name,formatted_address,formatted_phone_number,website,url",
        }
        resp = self.session.get(DETAILS_URL, params=params, timeout=20)
        data = resp.json()
        if data.get("status") != "OK":
            return {}
        return data.get("result", {})
