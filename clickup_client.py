# clickup_client.py
import logging
from typing import Dict, List, Optional, Any

import requests

from config import settings

logger = logging.getLogger("app")


# Статусы (должны совпадать с тем, что настраиваем в листе)
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
REPLIED_STATUS = "REPLIED"


class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self) -> None:
        self.team_id: str = str(settings.CLICKUP_TEAM_ID)
        self.space_id: str = str(settings.CLICKUP_SPACE_ID)
        self.headers = {
            "Authorization": settings.CLICKUP_API_TOKEN,
            "Content-Type": "application/json",
        }

    # -----------------------------
    # HTTP helpers
    # -----------------------------
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

    # -----------------------------
    # Lists (Boards)
    # -----------------------------
    def _lists_in_space(self) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        return data.get("lists", []) or []

    def _find_list_id_by_name(self, name: str) -> Optional[str]:
        for lst in self._lists_in_space():
            if lst.get("name") == name:
                return str(lst.get("id"))
        return None

    def create_list_in_space(self, name: str) -> str:
        """
        Создаёт List в текущем Space. Возвращает list_id.
        """
        url = f"{self.BASE_URL}/space/{self.space_id}/list"
        data = self._post(url, {"name": name})
        list_id = str(data["id"])
        return list_id

    def set_list_statuses(self, list_id: str) -> None:
        """
        Включает override_statuses и задаёт нужные «колонки» (статусы).
        Типы: open/custom/closed.
        """
        url = f"{self.BASE_URL}/list/{list_id}"
        payload = {
            "override_statuses": True,
            "statuses": [
                {"status": NEW_STATUS,     "type": "open",   "color": "#6b6b6b"},
                {"status": READY_STATUS,   "type": "custom", "color": "#8c78ff"},
                {"status": SENT_STATUS,    "type": "custom", "color": "#4aa3ff"},
                {"status": REPLIED_STATUS, "type": "closed", "color": "#2ecc71"},
            ],
        }
        try:
            self._put(url, payload)
        except Exception as e:
            logger.warning("ClickUp set_list_statuses failed for list %s: %s", list_id, e)

    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Возвращает list_id для штата. Если листа нет — создаёт и настраивает статусы.
        """
        name = f"LEADS-{state}"
        list_id = self._find_list_id_by_name(name)
        if list_id:
            return list_id

        try:
            list_id = self.create_list_in_space(name)
            self.set_list_statuses(list_id)
            logger.info("ClickUp: created list %s for state %s", list_id, state)
            return list_id
        except Exception as e:
            logger.error("ClickUp create list failed for state %s: %s", state, e)
            raise

    # -----------------------------
    # Tasks
    # -----------------------------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        """
        Возвращает словарь {field_id: field_name} для листа.
        """
        url = f"{self.BASE_URL}/list/{list_id}/field"
        try:
            data = self._get(url)
        except Exception as e:
            logger.warning("ClickUp: cannot fetch fields for list %s: %s", list_id, e)
            return {}

        mapping: Dict[str, str] = {}
        for f in data or []:
            fid = str(f.get("id"))
            name = (f.get("name") or "").strip()
            if fid and name:
                mapping[fid] = name
        return mapping

    def _task_email_from_custom_fields(
        self,
        task: Dict[str, Any],
        field_map: Dict[str, str],
    ) -> Optional[str]:
        """
        Пытаемся извлечь email из custom_fields по названию (email/e-mail/...).
        """
        cf = task.get("custom_fields") or []
        candidates = {"email", "e-mail", "contact email", "mail"}
        best: Optional[str] = None

        for item in cf:
            fid = str(item.get("id") or "")
            value = item.get("value")
            if value in (None, "", []):
                continue
            fname = (field_map.get(fid, "") or "").lower()
            if any(k in fname for k in candidates):
                # ClickUp может вернуть value как строку или словарь/список — приведём к строке
                best = value if isinstance(value, str) else str(value)
                break

        return best

    def _normalize_task(self, task: Dict[str, Any], field_map: Dict[str, str]) -> Dict[str, Any]:
        """
        Приводим задачу к нашему «лиду».
        Возвращаем:
          - task_id
          - clinic_name (из name)
          - status
          - email (если нашли)
        """
        task_id = str(task.get("id"))
        name = task.get("name") or ""
        status = (task.get("status") or {}).get("status") or ""
        email_val = self._task_email_from_custom_fields(task, field_map)
        return {
            "task_id": task_id,
            "clinic_name": name,
            "status": status,
            "email": email_val,
        }

    def get_list_tasks_raw(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Сырые задачи листа (включая закрытые).
        """
        url = f"{self.BASE_URL}/list/{list_id}/task"
        params = {
            "include_closed": "true",
            "subtasks": "true",
            "page": 0,
        }
        data = self._get(url, params=params)
        return data.get("tasks", []) or []

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Нормализованные лиды из листа.
        """
        field_map = self._list_custom_fields_map(list_id)
        tasks = self.get_list_tasks_raw(list_id)
        return [self._normalize_task(t, field_map) for t in tasks]

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        """
        Переводит задачу в указанный статус.
        """
        url = f"{self.BASE_URL}/task/{task_id}"
        payload = {"status": status}
        self._put(url, payload)

    def _all_state_lists(self) -> List[str]:
        """
        Возвращает list_id всех листов LEADS-* в текущем Space.
        """
        ids: List[str] = []
        for lst in self._lists_in_space():
            name = (lst.get("name") or "")
            if name.startswith("LEADS-"):
                ids.append(str(lst.get("id")))
        return ids

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Находит первую задачу по email среди всех листов LEADS-* текущего Space.
        Возвращает нормализованный dict (как в get_leads_from_list) либо None.
        """
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

# Экспортируем константы, чтобы другие модули могли импортировать:
__all__ = [
    "clickup_client",
    "NEW_STATUS",
    "READY_STATUS",
    "SENT_STATUS",
    "REPLIED_STATUS",
]
