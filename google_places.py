# google_places.py
import os
import logging
from typing import List, Dict, Any

import requests

log = logging.getLogger("google_places")

API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")


class GooglePlacesClient:
    BASE = "https://maps.googleapis.com/maps/api/place/textsearch/json"

    def search_places(self, query: str) -> List[Dict[str, Any]]:
        """
        Возвращаем всегда САМ запрос, без лимита 20 — просто все страницы.
        """
        params = {
            "query": query,
            "key": API_KEY,
        }
        out: List[Dict[str, Any]] = []
        url = self.BASE
        while True:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            results = data.get("results") or []
            for item in results:
                out.append(
                    {
                        "place_id": item.get("place_id"),
                        "name": item.get("name"),
                        "formatted_address": item.get("formatted_address"),
                        # остальные поля вытащим потом через details, если нужно
                    }
                )
            token = data.get("next_page_token")
            if not token:
                break
            # гуглу надо чуть подождать, но railway нам не даст спать —
            # поэтому просто второй запрос с токеном
            params = {"pagetoken": token, "key": API_KEY}
        return out
