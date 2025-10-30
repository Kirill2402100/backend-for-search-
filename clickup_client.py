# clickup_client.py
import os
import logging
from typing import Dict, Any, List, Optional

import requests

log = logging.getLogger("clickup")

CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "").strip()
CLICKUP_SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "").strip()
CLICKUP_TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "").strip()
CLICKUP_LIST_PREFIX = os.getenv("CLICKUP_LIST_PREFIX", "LEADS-")

API_BASE = "https://api.clickup.com/api/v2"

# статусы, которые ждёт весь остальной код
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"

# наши 5 обязательных кастомных полей
REQUIRED_FIELDS = {
    "email": {
        "name": "Email",
        "type": "text",
    },
    "website": {
        "name": "Website",
        "type": "text",
    },
    "facebook": {
        "name": "Facebook",
        "type": "text",
    },
    "instagram": {
        "name": "Instagram",
        "type": "text",
    },
    "linkedin": {
        "name": "LinkedIn",
        "type": "text",
    },
}


class ClickUpError(RuntimeError):
    pass


class ClickUpClient:
    def __init__(self, token: str):
        if not token:
            raise ClickUpError("CLICKUP_API_TOKEN is empty")
        self.token = token
        # кэш: list_id -> {custom_field_name_lower: field_id}
        self._fields_cache: Dict[str, Dict[str, str]] = {}

    # ------------- низкоуровневые штуки -------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    def _get(self, url: str, **kwargs) -> Any:
        r = requests.get(url, headers=self._headers(), timeout=30, **kwargs)
        if r.status_code >= 400:
            raise ClickUpError(f"GET {url} -> {r.status_code} {r.text}")
        return r.json()

    def _post(self, url: str, json: Any) -> Any:
        r = requests.post(url, headers=self._headers(), json=json, timeout=30)
        if r.status_code >= 400:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")
        return r.json()

    def _put(self, url: str, json: Any) -> Any:
        r = requests.put(url, headers=self._headers(), json=json, timeout=30)
        if r.status_code >= 400:
            raise ClickUpError(f"PUT {url} -> {r.status_code} {r.text}")
        return r.json()

    # ------------- работа со списками -------------
    def _list_by_name_in_space(self, space_id: str, name: str) -> Optional[str]:
        """
        Ищем list в space по имени. Возвращаем list_id или None.
        """
        url = f"{API_BASE}/space/{space_id}/list"
        data = self._get(url)
        for lst in data.get("lists", []):
            if lst.get("name") == name:
                return lst.get("id")
        return None

    def _create_list_in_space(self, space_id: str, name: str) -> str:
        """
        Создаём list со всеми нужными статусами.
        """
        url = f"{API_BASE}/space/{space_id}/list"
        payload = {
            "name": name,
            "content": "",
            # включаем только наши статусы
            "statuses": [
                {"status": NEW_STATUS, "color": "#d3d3d3", "type": "open"},
                {"status": READY_STATUS, "color": "#6f52ed", "type": "open"},
                {"status": SENT_STATUS, "color": "#1cc4f7", "type": "open"},
                {"status": INVALID_STATUS, "color": "#ff5e57", "type": "open"},
                {"status": REPLIED_STATUS, "color": "#00b894", "type": "closed"},
            ],
        }
        data = self._post(url, json=payload)
        list_id = data.get("id")
        if not list_id:
            raise ClickUpError(f"cannot create list in space {space_id}")
        log.info("created list %s in space %s", list_id, space_id)
        return list_id

    def get_or_create_list_for_state(self, state: str) -> str:
        """
        LEADS-NY, LEADS-TX и т.п.
        """
        if not CLICKUP_SPACE_ID:
            raise ClickUpError("CLICKUP_SPACE_ID is empty")

        list_name = f"{CLICKUP_LIST_PREFIX}{state.upper()}"
        list_id = self._list_by_name_in_space(CLICKUP_SPACE_ID, list_name)
        if list_id:
            # всё равно убедимся, что кастомные поля есть
            self._ensure_required_fields(list_id)
            return list_id

        # создаём
        list_id = self._create_list_in_space(CLICKUP_SPACE_ID, list_name)
        # и сразу поля
        self._ensure_required_fields(list_id)
        return list_id

    # ------------- кастомные поля -------------
    def _fetch_list_fields(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{API_BASE}/list/{list_id}/field"
        data = self._get(url)
        return data.get("fields", [])

    def _create_field_on_list(self, list_id: str, name: str, ftype: str = "text") -> str:
        url = f"{API_BASE}/list/{list_id}/field"
        payload = {
            "name": name,
            "type": ftype,  # text
        }
        data = self._post(url, json=payload)
        fid = data.get("id")
        if not fid:
            raise ClickUpError(f"cannot create field {name} on list {list_id}")
        log.info("created custom field %s (%s) on list %s", fid, name, list_id)
        return fid

    def _ensure_required_fields(self, list_id: str) -> Dict[str, str]:
        """
        Убеждаемся, что на листе есть 5 наших полей.
        Возвращаем словарь: lower_name -> field_id
        """
        if list_id in self._fields_cache:
            return self._fields_cache[list_id]

        existing = self._fetch_list_fields(list_id)
        by_name_lower: Dict[str, str] = {}
        for f in existing:
            nm = (f.get("name") or "").strip().lower()
            if nm:
                by_name_lower[nm] = f.get("id")

        for key, cfg in REQUIRED_FIELDS.items():
            field_name = cfg["name"]
            low = field_name.lower()
            if low not in by_name_lower:
                # создаём
                fid = self._create_field_on_list(list_id, field_name, cfg["type"])
                by_name_lower[low] = fid

        self._fields_cache[list_id] = by_name_lower
        return by_name_lower

    # ------------- задачи -------------
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
            # ClickUp ждёт список объектов {id, value}
            cf_items = []
            for fid, val in custom_fields.items():
                if val is None or val == "":
                    continue
                cf_items.append({"id": fid, "value": val})
            if cf_items:
                payload["custom_fields"] = cf_items

        data = self._post(url, json=payload)
        tid = data.get("id")
        if not tid:
            raise ClickUpError(f"cannot create task on list {list_id}")
        return tid

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{API_BASE}/task/{task_id}"
        self._put(url, json={"status": status})
        log.info("task %s moved to %s", task_id, status)

    # полный список задач листа (с пагинацией)
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        page = 0
        while True:
            url = f"{API_BASE}/list/{list_id}/task?subtasks=true&page={page}"
            data = self._get(url)
            tasks = data.get("tasks", [])
            if not tasks:
                break
            for t in tasks:
                out.append(
                    {
                        "task_id": t.get("id"),
                        "name": t.get("name"),
                        "status": t.get("status", {}).get("status") or t.get("status"),
                        # custom_fields тоже пригодятся
                        "custom_fields": t.get("custom_fields", []),
                    }
                )
            page += 1
        return out

    # ------------- поиск по email (для /replies) -------------
    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Простой вариант: проходимся по спискам в space и ищем в кастомных полях Email.
        Это не ультра-оптимально, но у тебя объёмы небольшие.
        """
        if not CLICKUP_SPACE_ID:
            return None

        # получаем списки в space
        url = f"{API_BASE}/space/{CLICKUP_SPACE_ID}/list"
        data = self._get(url)
        lists = data.get("lists", [])

        email_addr_low = (email_addr or "").strip().lower()
        if not email_addr_low:
            return None

        for lst in lists:
            lid = lst.get("id")
            if not lid:
                continue
            fields_map = self._ensure_required_fields(lid)
            email_field_id = fields_map.get("email")
            if not email_field_id:
                continue

            tasks = self.get_leads_from_list(lid)
            for t in tasks:
                for cf in t.get("custom_fields", []):
                    if cf.get("id") == email_field_id:
                        val = (cf.get("value") or "").strip().lower()
                        if val == email_addr_low:
                            return {
                                "task_id": t["task_id"],
                                "clinic_name": t["name"],
                            }
        return None

    # ------------- upsert для твоего leads.py -------------
    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> str:
        """
        lead: {
          "name": ...,
          "email": ...,
          "website": ...,
          "facebook": ...,
          "instagram": ...,
          "linkedin": ...,
        }
        Всегда создаём новую задачу со статусом NEW.
        """
        name = lead.get("name") or "Unknown clinic"
        fields_map = self._ensure_required_fields(list_id)

        cf_values: Dict[str, Any] = {}

        def put_if(field_key: str, val: Optional[str]):
            if not val:
                return
            fid = fields_map.get(REQUIRED_FIELDS[field_key]["name"].lower())
            # но мы в _ensure_required_fields сделали ключи по lower name,
            # значит можно проще:
        # поправим: fields_map уже по lower name
        # поэтому возьмём вот так:
        for logical_key, cfg in REQUIRED_FIELDS.items():
            val = lead.get(logical_key)
            if not val:
                continue
            fid = fields_map.get(cfg["name"].lower())
            if fid:
                cf_values[fid] = val

        task_id = self.create_task(
            list_id=list_id,
            name=name,
            status=NEW_STATUS,
            custom_fields=cf_values,
        )
        log.info("created lead task %s on list %s (%s)", task_id, list_id, name)
        return task_id


# единственный экземпляр, как раньше
clickup_client = ClickUpClient(CLICKUP_API_TOKEN)
