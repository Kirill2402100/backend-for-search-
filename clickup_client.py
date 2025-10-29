# clickup_client.py
import logging
from typing import Dict, List, Optional, Any

import requests
from config import settings

logger = logging.getLogger("app")

# Константы статусов (совпадают с колонками в листе)
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"     # <— добавлен для совместимости с send.py
REPLIED_STATUS = "REPLIED"


class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self) -> None:
        # team_id сейчас не используется, но оставим для будущих методов
        self.team_id: str = str(settings.CLICKUP_TEAM_ID)
        self.space_id: str = str(settings.CLICKUP_SPACE_ID)
        self.headers = {
            "Authorization": settings.CLICKUP_API_TOKEN,
            "Content-Type": "application/json",
        }

    # ---------- HTTP helpers ----------
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = requests.get(url, headers=self.headers, params=params or {}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"ClickUp GET {url} -> {r.status_code}: {r.text}")
        return r.json()

    def _post(self, url: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(url, headers=self.headers, json=json_body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"ClickUp POST {url} -> {r.status_code}: {r.text}")
        return r.json()

    def _put(self, url: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.put(url, headers=self.headers, json=json_body, timeout=30)
        if r.status_code not in (200, 204):
            raise RuntimeError(f"ClickUp PUT {url} -> {r.status_code}: {r.text}")
        return r.json() if r.text else {}

    # ---------- Lists ----------
    def _lists_in_space(self) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        return data.get("lists", []) or []

    def _find_list_id_by_name(self, name: str) -> Optional[str]:
        for lst in self._lists_in_space():
            if (lst.get("name") or "") == name:
                return str(lst.get("id"))
        return None

    def create_list_in_space(self, name: str) -> str:
        url = f"{self.BASE_URL}/space/{self.space_id}/list"
        data = self._post(url, {"name": name})
        return str(data["id"])

    def set_list_statuses(self, list_id: str) -> None:
        """
        Включаем override_statuses и задаём колонки (статусы).
        Типы допустимые ClickUp: open / custom / closed
        """
        url = f"{self.BASE_URL}/list/{list_id}"
        payload = {
            "override_statuses": True,
            "statuses": [
                {"status": NEW_STATUS,      "type": "open",   "color": "#6b6b6b"},
                {"status": READY_STATUS,    "type": "custom", "color": "#8c78ff"},
                {"status": SENT_STATUS,     "type": "custom", "color": "#4aa3ff"},
                {"status": INVALID_STATUS,  "type": "custom", "color": "#ff8c66"},
                {"status": REPLIED_STATUS,  "type": "closed", "color": "#2ecc71"},
            ],
        }
        try:
            self._put(url, payload)
        except Exception as e:
            logger.warning("ClickUp set_list_statuses failed for list %s: %s", list_id, e)

    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Возвращает list_id для штата. Если нет — создаёт лист LEADS-{STATE}
        и настраивает колонки.
        """
        name = f"LEADS-{state}"
        list_id = self._find_list_id_by_name(name)
        if list_id:
            return list_id
        list_id = self.create_list_in_space(name)
        self.set_list_statuses(list_id)
        logger.info("ClickUp: created list %s for state %s", list_id, state)
        return list_id

    # ---------- Tasks ----------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        url = f"{self.BASE_URL}/list/{list_id}/field"
        try:
            data = self._get(url)
        except Exception as e:
            logger.warning("ClickUp: cannot fetch fields for list %s: %s", list_id, e)
            return {}
        mapping: Dict[str, str] = {}
        for f in data or []:
            fid = str(f.get("id") or "")
            name = (f.get("name") or "").strip()
            if fid and name:
                mapping[fid] = name
        return mapping

    def _task_email_from_custom_fields(
        self,
        task: Dict[str, Any],
        field_map: Dict[str, str],
    ) -> Optional[str]:
        cf = task.get("custom_fields") or []
        candidates = {"email", "e-mail", "contact email", "mail"}
        for item in cf:
            fid = str(item.get("id") or "")
            value = item.get("value")
            if value in (None, "", []):
                continue
            fname = (field_map.get(fid, "") or "").lower()
            if any(k in fname for k in candidates):
                return value if isinstance(value, str) else str(value)
        return None

    def _normalize_task(self, task: Dict[str, Any], field_map: Dict[str, str]) -> Dict[str, Any]:
        return {
            "task_id": str(task.get("id")),
            "clinic_name": task.get("name") or "",
            "status": (task.get("status") or {}).get("status") or "",
            "email": self._task_email_from_custom_fields(task, field_map),
        }

    def get_list_tasks_raw(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/list/{list_id}/task"
        params = {"include_closed": "true", "subtasks": "true", "page": 0}
        data = self._get(url, params=params)
        return data.get("tasks", []) or []

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        field_map = self._list_custom_fields_map(list_id)
        return [self._normalize_task(t, field_map) for t in self.get_list_tasks_raw(list_id)]

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{self.BASE_URL}/task/{task_id}"
        self._put(url, {"status": status})

    def _all_state_lists(self) -> List[str]:
        ids: List[str] = []
        for lst in self._lists_in_space():
            if (lst.get("name") or "").startswith("LEADS-"):
                ids.append(str(lst.get("id")))
        return ids

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        email_lc = (email_addr or "").strip().lower()
        if not email_lc:
            return None
        for list_id in self._all_state_lists():
            field_map = self._list_custom_fields_map(list_id)
            for task in self.get_list_tasks_raw(list_id):
                lead = self._normalize_task(task, field_map)
                if (lead.get("email") or "").strip().lower() == email_lc:
                    return lead
        return None


# Глобальный инстанс
clickup_client = ClickUpClient()

# Экспортируем то, что используют другие модули
__all__ = [
    "clickup_client",
    "NEW_STATUS",
    "READY_STATUS",
    "SENT_STATUS",
    "INVALID_STATUS",
    "REPLIED_STATUS",
]
