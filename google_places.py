# google_places.py
import os
import time
import logging
from typing import List, Dict, Any

import requests

log = logging.getLogger("google_places")

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
            log.error("GooglePlacesClient: API key is empty")

    def _search_pages(self, query: str, max_pages: int = 4) -> List[Dict[str, Any]]:
        if not self.api_key:
            return []

        params = {"query": query, "key": self.api_key}
        all_results: List[Dict[str, Any]] = []
        page = 0

        while True:
            r = SESSION.get(BASE_URL, params=params, timeout=15)
            data = r.json()
            status = data.get("status")
            if status == "REQUEST_DENIED":
                log.error("Google denied %s: %s", query, data.get("error_message"))
                break
            if status not in ("OK", "ZERO_RESULTS"):
                log.warning("Google status %s for %s", status, query)
                break

            results = data.get("results", [])
            all_results.extend(results)

            next_token = data.get("next_page_token")
            page += 1
            if not next_token or page >= max_pages:
                break

            time.sleep(2)
            params = {"pagetoken": next_token, "key": self.api_key}

        return all_results

    def search(self, query: str) -> List[Dict[str, Any]]:
        raw = self._search_pages(query)
        places: List[Dict[str, Any]] = []
        for item in raw:
            places.append(
                {
                    "place_id": item.get("place_id"),
                    "name": item.get("name"),
                    "address": item.get("formatted_address"),
                    "website": "",     # textsearch почти никогда не присылает
                    "facebook": "",
                    "instagram": "",
                    "linkedin": "",
                    "source": "google",
                }
            )
        log.info("google (new) %r -> %d places", query, len(places))
        return places
