# clickup_client.py
import os
import logging
from typing import Dict, Any, List, Optional

import requests

log = logging.getLogger("clickup")

CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "").strip()
CLICKUP_TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "").strip()
CLICKUP_SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "").strip()
CLICKUP_TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "").strip()

API_BASE = "https://api.clickup.com/api/v2"

# наши статусы
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"

# наши нужные кастомные поля
REQUIRED_FIELDS = {
    "Email": {"type": "short_text"},
    "Website": {"type": "url"},
    "Facebook": {"type": "url"},
    "Instagram": {"type": "url"},
    "LinkedIn": {"type": "url"},
}


class ClickUpError(Exception):
    pass


class ClickUpClient:
    def __init__(self, token: str):
        self.token = token
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": self.token,
            "Content-Type": "application/json",
        })

    # ---------- low level ----------
    def _get(self, url: str, **kwargs) -> Any:
        r = self._session.get(url, **kwargs)
        if r.status_code >= 400:
            raise ClickUpError(f"GET {url} -> {r.status_code} {r.text}")
        return r.json()

    def _post(self, url: str, json: Any) -> Any:
        r = self._session.post(url, json=json)
        if r.status_code >= 400:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")
        return r.json()

    # ---------- lists ----------
    def _find_list_by_name(self, space_id: str, name: str) -> Optional[str]:
        # GET /space/{space_id}/list
        url = f"{API_BASE}/space/{space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            if item.get("name") == name:
                return item.get("id")
        return None

    def _create_list(self, space_id: str, name: str) -> str:
        url = f"{API_BASE}/space/{space_id}/list"
        payload = {"name": name}
        data = self._post(url, json=payload)
        return data["id"]

    def get_or_create_list_for_state(self, state: str) -> str:
        if not CLICKUP_SPACE_ID:
            raise ClickUpError("CLICKUP_SPACE_ID is not set")

        list_name = f"LEADS-{state}"
        existing = self._find_list_by_name(CLICKUP_SPACE_ID, list_name)
        if existing:
            # убедимся, что на нём есть нужные поля
            self._ensure_required_fields(existing)
            return existing

        # если хотим — можем копировать из шаблона, но это опционально
        new_list_id = self._create_list(CLICKUP_SPACE_ID, list_name)
        self._ensure_required_fields(new_list_id)
        return new_list_id

    # ---------- custom fields ----------
    def _list_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{API_BASE}/list/{list_id}/field"
        data = self._get(url)
        return data.get("fields", [])

    def _create_field_on_list(self, list_id: str, name: str, field_type: str) -> Optional[str]:
        """
        Создаём поле. Если ClickUp вернул 4xx — просто предупреждаем и не падаем.
        """
        url = f"{API_BASE}/list/{list_id}/field"
        payload = {
            "name": name,
            "type": field_type,
        }
        r = self._session.post(url, json=payload)
        if r.status_code >= 400:
            log.warning("cannot create field %s on list %s (no id in resp)", name, list_id)
            return None
        data = r.json()
        return data.get("id")

    def _ensure_required_fields(self, list_id: str) -> Dict[str, str]:
        """
        Убеждаемся, что на листе есть наши поля. Возвращаем map: имя -> field_id
        """
        existing = self._list_custom_fields(list_id)
        name_to_id = {f.get("name"): f.get("id") for f in existing if f.get("id")}

        for fname, cfg in REQUIRED_FIELDS.items():
            if fname in name_to_id:
                continue
            fid = self._create_field_on_list(list_id, fname, cfg["type"])
            if fid:
                name_to_id[fname] = fid
        return name_to_id

    # ---------- tasks ----------
    def create_task(
        self,
        list_id: str,
        name: str,
        status: str = NEW_STATUS,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> str:
        url = f"{API_BASE}/list/{list_id}/task"
        payload: Dict[str, Any] = {
            "name": name,
            "status": status,
        }

        if custom_fields:
            # ClickUp ждёт массив с id/ value
            payload["custom_fields"] = [
                {"id": fid, "value": val} for fid, val in custom_fields.items() if val is not None
            ]

        r = self._session.post(url, json=payload)
        if r.status_code == 400 and "Custom field usages exceeded" in r.text:
            # повторяем без custom_fields
            log.warning("ClickUp custom field limit reached on list %s -> creating task without custom fields", list_id)
            payload.pop("custom_fields", None)
            r = self._session.post(url, json=payload)

        if r.status_code >= 400:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")

        data = r.json()
        return data["id"]

    def update_task_custom_fields(self, task_id: str, custom_fields: Dict[str, Any]) -> None:
        """
        Обновляет кастомные поля уже созданной задачи.
        Если снова упираемся в лимит — просто предупреждаем.
        """
        url = f"{API_BASE}/task/{task_id}"
        payload = {
            "custom_fields": [
                {"id": fid, "value": val} for fid, val in custom_fields.items() if val is not None
            ]
        }
        r = self._session.put(url, json=payload)
        if r.status_code == 400 and "Custom field usages exceeded" in r.text:
            log.warning("cannot update custom fields for task %s (limit reached)", task_id)
            return
        if r.status_code >= 400:
            raise ClickUpError(f"PUT {url} -> {r.status_code} {r.text}")

    # ---------- business ----------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{API_BASE}/list/{list_id}/task"
        data = self._get(url)
        return data.get("tasks", [])

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> None:
        """
        Простейший вариант: сейчас просто создаём всегда.
        Можно сделать поиск по имени/сайту и обновлять, если надо.
        """
        name = lead["name"]
        # гарантируем поля (могут не создаться, если у плана лимит — мы это переживём)
        field_map = self._ensure_required_fields(list_id)

        custom_values: Dict[str, Any] = {}
        if field_map.get("Email"):
            custom_values[field_map["Email"]] = lead.get("email") or ""
        if field_map.get("Website"):
            custom_values[field_map["Website"]] = lead.get("website") or ""
        if field_map.get("Facebook"):
            custom_values[field_map["Facebook"]] = lead.get("facebook") or ""
        if field_map.get("Instagram"):
            custom_values[field_map["Instagram"]] = lead.get("instagram") or ""
        if field_map.get("LinkedIn"):
            custom_values[field_map["LinkedIn"]] = lead.get("linkedin") or ""

        task_id = self.create_task(
            list_id=list_id,
            name=name,
            status=NEW_STATUS,
            custom_fields=custom_values,
        )
        log.info("created lead task %s on list %s (%s)", task_id, list_id, name)

    # вспомогательные, которые уже были у тебя
    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{API_BASE}/task/{task_id}"
        payload = {"status": status}
        r = self._session.put(url, json=payload)
        if r.status_code >= 400:
            raise ClickUpError(f"PUT {url} -> {r.status_code} {r.text}")

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        # можно будет дописать позже
        return None


clickup_client = ClickUpClient(CLICKUP_API_TOKEN)
