# google_places.py
import os
import time
import logging
import requests
from typing import List, Dict, Any

log = logging.getLogger("google_places")

# читаем оба варианта имён, чтобы не было "0 places" из-за названия
API_KEY = (
    os.getenv("GOOGLE_PLACES_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or ""
).strip()

BASE_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
SESSION = requests.Session()


class GooglePlacesClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or API_KEY).strip()
        if not self.api_key:
            log.error("GooglePlacesClient: API key is empty! Set GOOGLE_PLACES_API_KEY or GOOGLE_API_KEY")

    def _text_search_all_pages(self, query: str, max_pages: int = 4) -> List[Dict[str, Any]]:
        """
        Собираем все страницы textsearch.
        """
        if not self.api_key:
            return []

        results: List[Dict[str, Any]] = []
        params = {
            "query": query,
            "key": self.api_key,
            # можно добавить: "region": "us"
        }
        page = 0

        while True:
            r = SESSION.get(BASE_URL, params=params, timeout=15)
            data = r.json()

            status = data.get("status")
            if status == "REQUEST_DENIED":
                log.error("Google Places denied request for %s: %s", query, data.get("error_message"))
                break
            if status not in ("OK", "ZERO_RESULTS"):
                log.warning("Google Places returned %s for %s", status, query)
                break

            batch = data.get("results", [])
            results.extend(batch)

            next_token = data.get("next_page_token")
            page += 1
            if not next_token:
                break
            if page >= max_pages:
                break

            # у Google нужно подождать перед следующим листом
            time.sleep(2)
            params = {
                "pagetoken": next_token,
                "key": self.api_key,
            }

        return results

    def search(self, query: str) -> List[Dict[str, Any]]:
        raw = self._text_search_all_pages(query)
        places: List[Dict[str, Any]] = []
        for item in raw:
            places.append(
                {
                    "place_id": item.get("place_id"),
                    "name": item.get("name"),
                    "address": item.get("formatted_address"),
                    # textsearch почти никогда не даёт сайт/соцсети, поэтому будут пустые
                    "website": "",
                    "facebook": "",
                    "instagram": "",
                    "linkedin": "",
                    "source": "google",
                }
            )
        log.info("google (new) %r -> %d places", query, len(places))
        return places
