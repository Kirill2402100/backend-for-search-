# clickup_client.py
import logging
from typing import Any, Dict, List, Optional

import requests

from config import settings

logger = logging.getLogger("clickup")

API_BASE = "https://api.clickup.com/api/v2"

# статусы, которыми мы пользуемся по всему проекту
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"  # когда пришёл ответ по email

# имена кастомных полей, которые мы хотим хранить в таске
CF_CLINIC = "clinic"          # название клиники
CF_WEBSITE = "website"        # сайт
CF_EMAIL = "email"            # email
CF_PHONE = "phone"            # телефон
CF_SIGNATURE = "signature"    # кто писал / подпись


class ClickUpClient:
    def __init__(self, token: str, space_id: str, team_id: str):
        self.token = token
        self.space_id = space_id
        self.team_id = team_id
        self._headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    # ------------- низкоуровневые запросы -------------

    def _get(self, path: str, **params) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        r = requests.get(url, headers=self._headers, params=params or None, timeout=15)
        if not r.ok:
            raise RuntimeError(f"ClickUp error: {r.status_code} {r.text}")
        return r.json()

    def _post(self, path: str, json: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        r = requests.post(url, headers=self._headers, json=json, timeout=15)
        if not r.ok:
            raise RuntimeError(f"ClickUp error: {r.status_code} {r.text}")
        return r.json()

    def _put(self, path: str, json: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{API_BASE}{path}"
        r = requests.put(url, headers=self._headers, json=json, timeout=15)
        if not r.ok:
            raise RuntimeError(f"ClickUp error: {r.status_code} {r.text}")
        return r.json()

    # ------------- служебное -------------

    def _list_custom_fields_map(self, list_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Возвращает словарь вида:
        {
          "clinic": {...},
          "website": {...},
          ...
        }
        и главное — не падает, если ClickUp прислал что-то странное.
        """
        try:
            data = self._get(f"/list/{list_id}/field")
        except RuntimeError as e:
            logger.warning("cannot load list fields for %s: %s", list_id, e)
            return {}

        fields = data.get("fields") or []
        out: Dict[str, Dict[str, Any]] = {}
        for f in fields:
            # тут и был краш: f оказалось строкой
            if not isinstance(f, dict):
                continue
            name = (f.get("name") or "").strip().lower()
            if not name:
                continue
            out[name] = f
        return out

    def _ensure_statuses_for_list(self, list_id: str) -> None:
        """
        Мы хотим, чтобы в листе были 4 статуса: NEW, READY, SENT, INVALID.
        Если лист только что создан — мы их создаём.
        """
        # в ClickUp статусы задаются при создании листа,
        # поэтому тут чаще всего ничего делать не надо.
        # но пусть будет отдельная функция — на будущее.
        pass

    # ------------- публичные методы -------------

    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Находит или создаёт список LEADS-{state} в нужном Space.
        Возвращает list_id.
        """
        state = state.upper()
        target_name = f"LEADS-{state}"

        # 1. пробуем найти
        lists_data = self._get(f"/space/{self.space_id}/list")
        for lst in lists_data.get("lists", []):
            if lst.get("name") == target_name:
                return str(lst.get("id"))

        # 2. нет — создаём
        payload = {
            "name": target_name,
            "content": f"Leads for {state}",
            "statuses": [
                {"status": NEW_STATUS, "orderindex": 0, "color": "#d3d3d3"},
                {"status": READY_STATUS, "orderindex": 1, "color": "#6bc950"},
                {"status": SENT_STATUS, "orderindex": 2, "color": "#3388ff"},
                {"status": INVALID_STATUS, "orderindex": 3, "color": "#ff6666"},
            ],
        }
        created = self._post(f"/space/{self.space_id}/list", payload)
        list_id = str(created.get("id"))
        logger.info("created list %s for state %s", list_id, state)
        return list_id

    def create_lead_task(
        self,
        list_id: str,
        clinic_name: str,
        website: Optional[str] = None,
        email_: Optional[str] = None,
        phone: Optional[str] = None,
        signature: Optional[str] = None,
        status: str = NEW_STATUS,
    ) -> str:
        """
        Создаём задачу-лид и заполняем её кастомные поля, если они есть в листе.
        """
        fields_map = self._list_custom_fields_map(list_id)

        custom_fields: List[Dict[str, Any]] = []

        def _maybe_add(cf_name: str, value: Optional[str]):
            if not value:
                return
            fld = fields_map.get(cf_name)
            if not fld:
                return
            custom_fields.append(
                {
                    "id": fld["id"],
                    "value": value,
                }
            )

        _maybe_add("clinic", clinic_name)
        _maybe_add("website", website)
        _maybe_add("email", email_)
        _maybe_add("phone", phone)
        _maybe_add("signature", signature)

        payload = {
            "name": clinic_name,
            "status": status,
        }
        if custom_fields:
            payload["custom_fields"] = custom_fields

        data = self._post(f"/list/{list_id}/task", payload)
        return str(data.get("id"))

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        self._put(f"/task/{task_id}", {"status": status})

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Возвращаем список наших "лидов" в виде простых словарей:
        {
          "task_id": "...",
          "clinic_name": "...",
          "email": "...",
          "website": "...",
          "phone": "...",
          "status": "READY" / "SENT" / ...
        }
        """
        # загрузим кастомные поля (чтобы понимать id полей)
        fields_map = self._list_custom_fields_map(list_id)
        # забираем сами таски
        tasks_data = self._get(f"/list/{list_id}/task", archived=False)
        tasks = tasks_data.get("tasks", [])

        out: List[Dict[str, Any]] = []
        for t in tasks:
            task_id = str(t.get("id"))
            name = t.get("name") or ""
            status = (t.get("status") or {}).get("status") or NEW_STATUS

            cf_values = t.get("custom_fields") or []
            cf_by_id = {str(cf.get("id")): cf for cf in cf_values if isinstance(cf, dict)}

            def _get_cf(name: str) -> Optional[str]:
                fld = fields_map.get(name)
                if not fld:
                    return None
                val_obj = cf_by_id.get(str(fld["id"]))
                if not val_obj:
                    return None
                val = val_obj.get("value")
                if isinstance(val, str):
                    return val
                # иногда clickup шлёт {"value": {"text": "..."}}
                if isinstance(val, dict):
                    return val.get("text") or val.get("email") or val.get("phone")
                return None

            out.append(
                {
                    "task_id": task_id,
                    "clinic_name": name,
                    "email": _get_cf("email"),
                    "website": _get_cf("website"),
                    "phone": _get_cf("phone"),
                    "signature": _get_cf("signature"),
                    "status": status,
                }
            )

        return out

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Проходим по всем спискам в нашем Space и ищем таску, у которой кастомное поле email == email_addr.
        Это нужно, когда мы забираем ответы с почты.
        """
        lists_data = self._get(f"/space/{self.space_id}/list")
        for lst in lists_data.get("lists", []):
            list_id = str(lst.get("id"))
            fields_map = self._list_custom_fields_map(list_id)
            email_field = fields_map.get("email")
            if not email_field:
                continue

            tasks_data = self._get(f"/list/{list_id}/task", archived=False)
            for t in tasks_data.get("tasks", []):
                cf_values = t.get("custom_fields") or []
                for cf in cf_values:
                    if not isinstance(cf, dict):
                        continue
                    if str(cf.get("id")) != str(email_field["id"]):
                        continue
                    val = cf.get("value")
                    if isinstance(val, str) and val.lower() == email_addr.lower():
                        return {
                            "task_id": str(t.get("id")),
                            "clinic_name": t.get("name") or "",
                            "list_id": list_id,
                        }
        return None


# создаём синглтон, как и раньше
clickup_client = ClickUpClient(
    token=settings.CLICKUP_API_TOKEN,
    space_id=settings.CLICKUP_SPACE_ID,
    team_id=settings.CLICKUP_TEAM_ID,
)

# и экспортим статусы, чтобы другие файлы их импортировали
__all__ = [
    "clickup_client",
    "NEW_STATUS",
    "READY_STATUS",
    "SENT_STATUS",
    "INVALID_STATUS",
    "REPLIED_STATUS",
]
