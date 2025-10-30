# google_places.py
import os
import logging
import requests
from typing import List, Dict, Any

log = logging.getLogger("google_places")

# читаем оба варианта имён
API_KEY = (
    os.getenv("GOOGLE_PLACES_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
    or ""
).strip()

# ===== НОВЫЙ ЭНДПОИНТ ДЛЯ PLACES API (NEW) =====
BASE_URL = "https://places.googleapis.com/v1/places:searchText"


class GooglePlacesClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key or API_KEY).strip()
        if not self.api_key:
            log.error("GooglePlacesClient: API key is empty! Set GOOGLE_PLACES_API_KEY or GOOGLE_API_KEY")
        
        # Для нового API ключ передаётся в хедерах
        self.session = requests.Session()
        self.session.headers.update({
            "X-Goog-Api-Key": self.api_key,
            "Content-Type": "application/json"
        })

    def _text_search(self, query: str) -> List[Dict[str, Any]]:
        """
        Выполняет ОДИН запрос к searchText.
        Пейджинг здесь не поддерживается со стороны Google.
        """
        if not self.api_key:
            return []

        # ВАЖНО: Маска полей. Указываем, ЧТО мы хотим получить.
        # id = (старый place_id), displayName = (старое name)
        field_mask = "places.id,places.displayName,places.formattedAddress,places.websiteUri"

        # Новый API требует POST-запрос с JSON-телом
        payload = {
            "textQuery": query,
            "maxResultCount": 20,  # Это максимум для searchText
            "fieldMask": field_mask
        }

        try:
            r = self.session.post(BASE_URL, json=payload, timeout=15)
            # Проверка на 4xx/5xx ошибки
            r.raise_for_status()
            
            data = r.json()
            # Новый API возвращает { "places": [...] }
            return data.get("places", [])

        except requests.exceptions.HTTPError as e:
            log.error(
                "Google Places (New) HTTP error for query '%s': %s - %s",
                query, e.response.status_code, e.response.text
            )
            if "has not been used" in e.response.text or "API_NOT_ACTIVATED" in e.response.text:
                 log.error(
                     "!!! КРИТИЧНО: 'Places API (New)' не включен в Google Cloud Console. "
                     "Нужно зайти и включить именно 'Places API (New)'."
                 )
            return []
        except Exception as e:
            log.error("Google Places (New) generic error for query '%s': %s", query, e)
            return []

    def search(self, query: str) -> List[Dict[str, Any]]:
        # Вызываем нашу новую функцию
        raw_places = self._text_search(query)
        
        places: List[Dict[str, Any]] = []
        for item in raw_places:
            # 'name' теперь в 'displayName'
            name = (item.get("displayName") or {}).get("text", "")
            # 'place_id' теперь 'id'
            place_id = item.get("id")
            # 'formatted_address' теперь 'formattedAddress'
            address = item.get("formattedAddress")
            # 'website' теперь 'websiteUri' (и он теперь должен быть!)
            website = item.get("websiteUri", "")

            if not place_id or not name:
                continue  # Пропускаем неполные данные

            places.append(
                {
                    "place_id": place_id,
                    "name": name,
                    "address": address,
                    "website": website,
                    # Соцсетей по-прежнему нет в этом поиске
                    "facebook": "",
                    "instagram": "",
                    "linkedin": "",
                    "source": "google",
                }
            )
        log.info("google (new API) %r -> %d places", query, len(places))
        return places
