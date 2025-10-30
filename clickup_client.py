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

# статусы, которыми уже пользуется код
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"

# наши целевые поля
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
        # кэш: list_id -> {field_name_lower: field_id}
        self._fields_cache: Dict[str, Dict[str, str]] = {}

    # ---------------- low-level ----------------
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

    # ---------------- lists ----------------
    def _list_by_name_in_space(self, space_id: str, name: str) -> Optional[str]:
        url = f"{API_BASE}/space/{space_id}/list"
        data = self._get(url)
        for lst in data.get("lists", []):
            if lst.get("name") == name:
                return lst.get("id")
        return None

    def _create_list_in_space(self, space_id: str, name: str) -> str:
        url = f"{API_BASE}/space/{space_id}/list"
        payload = {
            "name": name,
            "content": "",
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
        if not CLICKUP_SPACE_ID:
            raise ClickUpError("CLICKUP_SPACE_ID is empty")

        list_name = f"{CLICKUP_LIST_PREFIX}{state.upper()}"
        list_id = self._list_by_name_in_space(CLICKUP_SPACE_ID, list_name)
        if not list_id:
            list_id = self._create_list_in_space(CLICKUP_SPACE_ID, list_name)

        # ВАЖНО: пробуем добавить поля, но НЕ падаем, если ClickUp не дал
        self._ensure_required_fields(list_id)
        return list_id

    # ---------------- custom fields ----------------
    def _fetch_list_fields(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{API_BASE}/list/{list_id}/field"
        data = self._get(url)
        return data.get("fields", [])

    def _create_field_on_list(self, list_id: str, name: str, ftype: str = "text") -> Optional[str]:
        """
        Пытаемся создать поле. Если ClickUp не даёт (план, права и т.п.) — просто логируем и возвращаем None.
        """
        url = f"{API_BASE}/list/{list_id}/field"
        payload = {"name": name, "type": ftype}
        r = requests.post(url, headers=self._headers(), json=payload, timeout=30)
        if r.status_code >= 400:
            log.warning("cannot create field %s on list %s -> %s %s", name, list_id, r.status_code, r.text[:200])
            return None
        data = r.json()
        fid = data.get("id")
        if not fid:
            log.warning("cannot create field %s on list %s (no id in resp)", name, list_id)
            return None
        log.info("created custom field %s (%s) on list %s", fid, name, list_id)
        return fid

    def _ensure_required_fields(self, list_id: str) -> Dict[str, str]:
        """
        Гарантируем максимум из того, что нам позволит ClickUp.
        Даже если ни одно поле создать не удалось — НЕ падаем.
        """
        if list_id in self._fields_cache:
            return self._fields_cache[list_id]

        existing = self._fetch_list_fields(list_id)
        by_name_lower: Dict[str, str] = {}
        for f in existing:
            nm = (f.get("name") or "").strip().lower()
            if nm:
                by_name_lower[nm] = f.get("id")

        # пробуем создать недостающие
        for _, cfg in REQUIRED_FIELDS.items():
            field_name = cfg["name"]
            low = field_name.lower()
            if low not in by_name_lower:
                fid = self._create_field_on_list(list_id, field_name, cfg["type"])
                if fid:
                    by_name_lower[low] = fid
                else:
                    # не смогли создать — просто живём дальше
                    pass

        self._fields_cache[list_id] = by_name_lower
        return by_name_lower

    # ---------------- tasks ----------------
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
            cf_items = []
            for fid, val in custom_fields.items():
                if not fid:
                    continue
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
                        "custom_fields": t.get("custom_fields", []),
                    }
                )
            page += 1
        return out

    # ---------------- search by email (for /replies) ----------------
    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        if not CLICKUP_SPACE_ID:
            return None

        email_addr_low = (email_addr or "").strip().lower()
        if not email_addr_low:
            return None

        # получаем все листы в space
        url = f"{API_BASE}/space/{CLICKUP_SPACE_ID}/list"
        data = self._get(url)
        lists = data.get("lists", [])

        for lst in lists:
            lid = lst.get("id")
            if not lid:
                continue
            fields_map = self._ensure_required_fields(lid)
            email_field_id = fields_map.get("email") or fields_map.get("email".lower())
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

    # ---------------- upsert used by leads.py ----------------
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
        for logical_key, cfg in REQUIRED_FIELDS.items():
            val = lead.get(logical_key)
            if not val:
                continue
            field_id = fields_map.get(cfg["name"].lower())
            if field_id:
                cf_values[field_id] = val
            else:
                # поле не получилось создать — просто пропускаем
                pass

        task_id = self.create_task(
            list_id=list_id,
            name=name,
            status=NEW_STATUS,
            custom_fields=cf_values,
        )
        log.info("created lead task %s on list %s (%s)", task_id, list_id, name)
        return task_id


# singleton
clickup_client = ClickUpClient(CLICKUP_API_TOKEN)
