# google_places.py
import os
import logging
from typing import Any, Dict, List

import requests

log = logging.getLogger("google_places")

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

class GooglePlacesError(Exception):
    pass


class GooglePlacesClient:
    """
    Клиент под новый Google Places API (New), текстовый поиск.
    Документация: https://developers.google.com/maps/documentation/places/web-service/search-text
    """
    def __init__(self) -> None:
        if not GOOGLE_PLACES_API_KEY:
            raise RuntimeError("GOOGLE_PLACES_API_KEY is not set")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.websiteUri"
        })

    def search(self, query: str) -> List[Dict[str, Any]]:
        url = "https://places.googleapis.com/v1/places:searchText"
        payload = {
            "textQuery": query,
            # можно сюда добавить "openNow": False/True, regionCode и т.д.
        }
        r = self.session.post(url, json=payload, timeout=20)
        if r.status_code >= 300:
            raise GooglePlacesError(f"google places error {r.status_code}: {r.text}")

        data = r.json()
        places = data.get("places", [])
        out: List[Dict[str, Any]] = []

        for p in places:
            place_id = p.get("id") or ""
            name = (p.get("displayName") or {}).get("text") or ""
            address = p.get("formattedAddress") or ""
            website = p.get("websiteUri") or ""

            out.append(
                {
                    "place_id": place_id,
                    "name": name,
                    "formatted_address": address,
                    "website": website,
                }
            )

        log.info("google (new) '%s' -> %d places", query, len(out))
        return out
