# clickup_client.py
import logging
from typing import Any, Dict, List, Optional

import requests

from config import settings

log = logging.getLogger("clickup")

CLICKUP_BASE = "https://api.clickup.com/api/v2"

# наши статусы
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"


class ClickUpClient:
    def __init__(self, token: str, team_id: str, space_id: str, template_list_id: Optional[str] = None):
        self.token = token
        self.team_id = team_id
        self.space_id = space_id
        self.template_list_id = template_list_id  # лист «БАЗА РАССЫЛКИ», откуда копируем поля

    # ------------- базовые -------------
    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    # ------------- вспомогательные -------------
    def _get_space_lists(self) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_BASE}/space/{self.space_id}/list"
        r = requests.get(url, headers=self._headers, timeout=15)
        r.raise_for_status()
        return r.json().get("lists", [])

    def _get_list_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Получаем список кастомных полей, которые ПРИКРЕПЛЕНЫ к листу.
        GET /list/{list_id}/field
        """
        url = f"{CLICKUP_BASE}/list/{list_id}/field"
        r = requests.get(url, headers=self._headers, timeout=15)
        r.raise_for_status()
        return r.json().get("fields", [])

    def _attach_field_to_list(self, list_id: str, field_id: str) -> None:
        """
        В ClickUp кастомное поле «подвязывается» к листу так:
        POST /list/{list_id}/field/{field_id}
        """
        url = f"{CLICKUP_BASE}/list/{list_id}/field/{field_id}"
        r = requests.post(url, headers=self._headers, timeout=15)
        if r.status_code not in (200, 201):
            # бывает 409 если уже есть — нам норм
            log.warning("cannot attach field %s to list %s: %s %s", field_id, list_id, r.status_code, r.text)

    def _clone_custom_fields_from_template(self, new_list_id: str) -> None:
        """
        Берём все поля с template_list_id и добавляем на new_list_id.
        Если в .env не задано CLICKUP_TEMPLATE_LIST_ID — просто пропускаем.
        """
        if not self.template_list_id:
            return
        try:
            template_fields = self._get_list_custom_fields(self.template_list_id)
        except Exception as e:
            log.warning("cannot read template list fields: %s", e)
            return
        for f in template_fields:
            fid = f.get("id")
            if not fid:
                continue
            self._attach_field_to_list(new_list_id, fid)

    # ------------- списки по штатам -------------
    def get_or_create_list_for_state(self, state: str) -> str:
        want_name = f"LEADS-{state.upper()}"
        # 1. поиск
        for lst in self._get_space_lists():
            if lst.get("name") == want_name:
                return str(lst["id"])

        # 2. создание
        url = f"{CLICKUP_BASE}/space/{self.space_id}/list"
        payload = {
            "name": want_name,
            "statuses": [
                {"status": NEW_STATUS, "type": "open"},
                {"status": READY_STATUS, "type": "open"},
                {"status": SENT_STATUS, "type": "done"},
                {"status": INVALID_STATUS, "type": "closed"},
            ],
        }
        r = requests.post(url, headers=self._headers, json=payload, timeout=15)
        if r.status_code >= 300:
            raise RuntimeError(f"ClickUp create list error: {r.status_code} {r.text}")
        new_id = str(r.json()["id"])
        log.info("created list %s for state %s", new_id, state)

        # 3. доклеиваем кастомные поля из шаблона
        self._clone_custom_fields_from_template(new_id)
        return new_id

    # ------------- задачи -------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_BASE}/list/{list_id}/task"
        r = requests.get(url, headers=self._headers, params={"subtasks": "true"}, timeout=15)
        r.raise_for_status()
        tasks = r.json().get("tasks", [])
        out: List[Dict[str, Any]] = []
        for t in tasks:
            out.append(
                {
                    "task_id": t.get("id"),
                    "name": t.get("name") or "",
                    "status": t.get("status", {}).get("status") or "",
                    "email": None,
                }
            )
        return out

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{CLICKUP_BASE}/task/{task_id}"
        r = requests.put(url, headers=self._headers, json={"status": status}, timeout=15)
        r.raise_for_status()

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        url_lists = f"{CLICKUP_BASE}/space/{self.space_id}/list"
        rl = requests.get(url_lists, headers=self._headers, timeout=15)
        rl.raise_for_status()
        for lst in rl.json().get("lists", []):
            lid = lst["id"]
            url_tasks = f"{CLICKUP_BASE}/list/{lid}/task"
            rt = requests.get(url_tasks, headers=self._headers, timeout=15)
            rt.raise_for_status()
            for t in rt.json().get("tasks", []):
                desc = (t.get("description") or "").lower()
                if email_addr.lower() in desc:
                    return {
                        "task_id": t["id"],
                        "clinic_name": t.get("name") or "",
                        "list_id": lid,
                    }
        return None

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> str:
        """
        Простой вариант: всегда создаём задачу.
        """
        name = lead.get("name") or "Clinic"
        email = (lead.get("email") or "").strip()
        address = lead.get("address") or ""
        phone = lead.get("phone") or ""
        website = lead.get("website") or ""
        source = lead.get("source") or ""
        place_id = lead.get("place_id") or ""

        status = READY_STATUS if email else NEW_STATUS

        desc_lines = []
        if address:
            desc_lines.append(f"Address: {address}")
        if phone:
            desc_lines.append(f"Phone: {phone}")
        if website:
            desc_lines.append(f"Website: {website}")
        if email:
            desc_lines.append(f"Email: {email}")
        if source:
            desc_lines.append(f"Source: {source}")
        if place_id:
            desc_lines.append(f"Place ID: {place_id}")

        description = "\n".join(desc_lines) or "Imported lead"

        url = f"{CLICKUP_BASE}/list/{list_id}/task"
        payload: Dict[str, Any] = {
            "name": name,
            "status": status,
            "description": description,
        }
        r = requests.post(url, headers=self._headers, json=payload, timeout=15)
        if r.status_code >= 300:
            log.error("ClickUp create task error: %s %s", r.status_code, r.text)
            raise RuntimeError(f"ClickUp create task error: {r.status_code} {r.text}")
        return str(r.json()["id"])


clickup_client = ClickUpClient(
    token=settings.CLICKUP_API_TOKEN,
    team_id=settings.CLICKUP_TEAM_ID,
    space_id=settings.CLICKUP_SPACE_ID,
    template_list_id=getattr(settings, "CLICKUP_TEMPLATE_LIST_ID", None),
)
