# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"

# статусы, которые мы хотим видеть на каждом «штатном» листе
DEFAULT_STATUSES = [
    {"status": "NEW", "type": "open", "color": "#d3d3d3"},
    {"status": "READY", "type": "open", "color": "#6a6ef7"},
    {"status": "SENT", "type": "done", "color": "#3ac35f"},
    {"status": "INVALID", "type": "closed", "color": "#f95c5c"},
]

# экспортируем ВСЁ, что может импортировать telegram_bot / send.py
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
REPLIED_STATUS = "REPLIED"
INVALID_STATUS = "INVALID"


class ClickUpError(RuntimeError):
    pass


class ClickUpClient:
    def __init__(
        self,
        token: str,
        team_id: str,
        space_id: str,
        template_list_id: Optional[str] = None,
    ) -> None:
        self.token = token
        self.team_id = team_id
        self.space_id = space_id
        # это может быть ПУСТО — тогда создаём простой лист
        self.template_list_id = (template_list_id or "").strip() or None

    # ----------------- внутреннее -----------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    def _raise_for(self, resp: requests.Response, msg: str) -> None:
        if not resp.ok:
            raise ClickUpError(f"{msg}: {resp.status_code} {resp.text}")

    # ----------------- листы -----------------
    def _create_list_plain(self, state: str) -> str:
        """Создаём обычный лист без шаблона."""
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        payload: Dict[str, Any] = {
            "name": f"LEADS-{state}",
            "statuses": DEFAULT_STATUSES,
        }
        r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
        self._raise_for(r, "ClickUp create list (plain)")
        data = r.json()
        return str(data["id"])

    def _create_list_from_template(self, state: str) -> Optional[str]:
        """Пробуем создать лист на основе ТЕМПЛЕЙТА (а не живого листа)."""
        if not self.template_list_id:
            return None

        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        payload: Dict[str, Any] = {
            "name": f"LEADS-{state}",
            "template_id": self.template_list_id,
        }
        r = requests.post(url, json=payload, headers=self._headers(), timeout=25)
        if r.status_code == 200:
            data = r.json()
            list_id = str(data["id"])
            # всё равно дожмём наши статусы
            self._ensure_statuses(list_id)
            return list_id

        # если это был ID живого листа — сюда и попадём
        log.warning(
            "ClickUp: can't create list from template_id=%s -> %s %s",
            self.template_list_id,
            r.status_code,
            r.text[:200],
        )
        return None

    def _ensure_statuses(self, list_id: str) -> None:
        url = f"{CLICKUP_API_BASE}/list/{list_id}"
        payload = {"statuses": DEFAULT_STATUSES}
        r = requests.put(url, json=payload, headers=self._headers(), timeout=20)
        if not r.ok:
            log.warning(
                "ClickUp: can't update statuses for list %s: %s %s",
                list_id,
                r.status_code,
                r.text[:200],
            )

    def get_or_create_list_for_state(self, state: str) -> str:
        """
        1. ищем список по имени LEADS-<STATE>
        2. если нет — создаём (сначала из шаблона, если задан)
        """
        # получить все листы в space
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        r = requests.get(url, headers=self._headers(), timeout=20)
        self._raise_for(r, "ClickUp get lists for space")
        data = r.json()
        target_name = f"LEADS-{state}"
        for lst in data.get("lists", []):
            if lst.get("name") == target_name:
                list_id = str(lst["id"])
                self._ensure_statuses(list_id)
                return list_id

        # если не нашли — создаём
        list_id = self._create_list_from_template(state)
        if list_id:
            return list_id

        return self._create_list_plain(state)

    # ----------------- чтение -----------------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        """
        Вернёт { "Email": "id...", ... } по данному листу.
        Если полей нет — {}.
        """
        url = f"{CLICKUP_API_BASE}/list/{list_id}/field"
        r = requests.get(url, headers=self._headers(), timeout=20)
        if not r.ok:
            log.warning(
                "ClickUp: can't fetch custom fields for list %s: %s %s",
                list_id,
                r.status_code,
                r.text[:200],
            )
            return {}

        fields = r.json().get("fields", [])
        out: Dict[str, str] = {}
        for f in fields:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id") or "")
            name = str(f.get("name") or "")
            if fid and name:
                out[name] = fid
        return out

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        tasks: List[Dict[str, Any]] = []
        page = 0
        field_map = self._list_custom_fields_map(list_id)

        while True:
            url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
            r = requests.get(
                url,
                params={"page": page, "subtasks": "true"},
                headers=self._headers(),
                timeout=25,
            )
            self._raise_for(r, "ClickUp get tasks from list")
            data = r.json()
            raw_tasks = data.get("tasks", [])
            if not raw_tasks:
                break

            for t in raw_tasks:
                item: Dict[str, Any] = {
                    "task_id": t["id"],
                    "name": t.get("name"),
                    "status": (t.get("status") or {}).get("status"),
                    "email": None,
                    "phone": None,
                    "website": None,
                }
                for cf in t.get("custom_fields", []):
                    cid = cf.get("id")
                    val = cf.get("value")
                    if not cid or val is None:
                        continue
                    for field_name, field_id in field_map.items():
                        if cid == field_id:
                            lname = field_name.lower()
                            if lname.startswith("email") or "электрон" in lname:
                                item["email"] = val
                            elif lname.startswith("номер") or "phone" in lname or "тел" in lname:
                                item["phone"] = val
                            elif lname.startswith("url") or "сайт" in lname:
                                item["website"] = val
                tasks.append(item)

            page += 1

        return tasks

    # ----------------- создание / upsert -----------------
    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> str:
        """
        Создаём задачу для клиники.
        ВСЕГДА создаём в NEW.
        Проставляем кастомные поля, если названия совпали.
        """
        field_map = self._list_custom_fields_map(list_id)
        custom_fields: List[Dict[str, Any]] = []

        def _maybe_add(field_title: str, value: Any) -> None:
            if not value:
                return
            fid = field_map.get(field_title)
            if not fid:
                return
            custom_fields.append({"id": fid, "value": value})

        _maybe_add("Номер телефона", lead.get("phone"))
        _maybe_add("Общий адрес электронной почты", lead.get("email"))
        _maybe_add("URL веб-сайта", lead.get("website"))
        _maybe_add("Выявленные возможности", lead.get("notes"))
        _maybe_add("Принадлежность к сети", lead.get("network"))

        payload: Dict[str, Any] = {
            "name": lead["name"],
            "status": NEW_STATUS,
        }
        if custom_fields:
            payload["custom_fields"] = custom_fields

        url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
        r = requests.post(url, json=payload, headers=self._headers(), timeout=25)
        self._raise_for(r, "ClickUp create lead task")
        data = r.json()
        return str(data["id"])

    # ----------------- поиск по email и смена статуса -----------------
    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        lists_url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        r = requests.get(lists_url, headers=self._headers(), timeout=20)
        if not r.ok:
            log.warning(
                "ClickUp: can't list lists for find_task_by_email: %s %s",
                r.status_code,
                r.text[:200],
            )
            return None

        for lst in r.json().get("lists", []):
            list_id = str(lst["id"])
            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                if t.get("email") and t["email"].lower() == email_addr.lower():
                    return {
                        "task_id": t["task_id"],
                        "clinic_name": t.get("name") or "",
                    }
        return None

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{CLICKUP_API_BASE}/task/{task_id}"
        r = requests.put(url, json={"status": status}, headers=self._headers(), timeout=20)
        self._raise_for(r, f"ClickUp move task {task_id} to {status}")


# глобальный клиент
clickup_client = ClickUpClient(
    token=os.environ.get("CLICKUP_API_TOKEN", ""),
    team_id=os.environ.get("CLICKUP_TEAM_ID", ""),
    space_id=os.environ.get("CLICKUP_SPACE_ID", ""),
    template_list_id=os.environ.get("CLICKUP_TEMPLATE_LIST_ID", ""),
)
