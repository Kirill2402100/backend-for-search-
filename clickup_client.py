# clickup_client.py
from __future__ import annotations

import os
import logging
from typing import Any, Dict, List, Optional

import requests
from config import settings

log = logging.getLogger("clickup")

API_BASE = "https://api.clickup.com/api/v2"

# Статусы, которые используем по всему проекту
NEW_STATUS = "NEW"                 # можно не использовать
READY_STATUS = "READY"
SENT_STATUS = "SENT"
REPLIED_STATUS = "REPLIED"
INVALID_STATUS = "INVALID"         # нужен send.py

# как будут называться листы для штатов
LIST_PREFIX = "LEADS-"


class ClickUpClient:
    def __init__(self, token: str, team_id: str, space_id: str):
        self.token = token
        self.team_id = str(team_id)
        self.space_id = str(space_id)
        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # ВСПОМОГАТЕЛЬНЫЕ HTTP
    # ------------------------------------------------------------------
    def _get(self, url: str, **kwargs) -> Dict[str, Any]:
        r = requests.get(url, headers=self.headers, timeout=15, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"ClickUp error: {r.status_code} {r.text}")
        return r.json()

    def _post(self, url: str, json: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(url, headers=self.headers, json=json, timeout=15)
        if r.status_code >= 400:
            raise RuntimeError(f"ClickUp error: {r.status_code} {r.text}")
        return r.json()

    def _put(self, url: str, json: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.put(url, headers=self.headers, json=json, timeout=15)
        if r.status_code >= 400:
            raise RuntimeError(f"ClickUp error: {r.status_code} {r.text}")
        return r.json()

    # ------------------------------------------------------------------
    # ЛИСТ ДЛЯ ШТАТА
    # ------------------------------------------------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Ищем лист LEADS-<STATE> в space.
        Если нет — создаём.
        Возвращаем list_id.
        """
        state = state.upper()
        target_name = f"{LIST_PREFIX}{state}"

        # 1) получить все листы в space
        url = f"{API_BASE}/space/{self.space_id}/list"
        data = self._get(url)

        for lst in data.get("lists", []):
            if lst.get("name") == target_name:
                return str(lst["id"])

        # 2) нет — создаём
        payload = {
            "name": target_name,
            "content": f"Leads for state {state}",
            "status": "open",
        }
        url = f"{API_BASE}/space/{self.space_id}/list"
        created = self._post(url, json=payload)
        return str(created["id"])

    # ------------------------------------------------------------------
    # CUSTOM FIELDS
    # ------------------------------------------------------------------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        """
        Возвращает словарь:
            {'clinic_name': <field_id>, 'email': <field_id>, ...}
        если поле есть в листе.
        Мы ориентируемся на человекочитаемые названия полей.
        """
        url = f"{API_BASE}/list/{list_id}/field"
        data = self._get(url)

        fields = data.get("fields", [])
        out: Dict[str, str] = {}

        for f in fields:
            if not isinstance(f, dict):
                # в старых ответах у тебя как раз была строка -> поэтому тут защита
                continue
            name = (f.get("name") or "").strip().lower()
            fid = str(f.get("id") or "")
            if not fid:
                continue

            if name in ("clinic", "clinic name", "clinic_name", "name"):
                out["clinic_name"] = fid
            elif name in ("email", "e-mail", "mail"):
                out["email"] = fid
            elif name in ("phone", "phone number", "телефон"):
                out["phone"] = fid
            elif name in ("website", "site", "web"):
                out["website"] = fid
            elif name in ("city",):
                out["city"] = fid
            elif name in ("source", "источник"):
                out["source"] = fid
            elif name in ("category", "категория", "type"):
                out["category"] = fid
            elif name in ("status",):
                out["status"] = fid

        return out

    # ------------------------------------------------------------------
    # ЧТЕНИЕ ЛИДОВ ИЗ ЛИСТА
    # ------------------------------------------------------------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Возвращает все задачи в листе в нормализованном виде.
        """
        url = f"{API_BASE}/list/{list_id}/task"
        data = self._get(url)

        field_map = self._list_custom_fields_map(list_id)
        tasks_out: List[Dict[str, Any]] = []

        for t in data.get("tasks", []):
            task_id = str(t.get("id") or "")
            name = t.get("name") or ""
            status = (t.get("status") or {}).get("status", "") or (t.get("status") or {}).get("status", "")

            norm: Dict[str, Any] = {
                "task_id": task_id,
                "name": name,
                "status": status,
                "clinic_name": name,  # по умолчанию
                "email": "",
                "phone": "",
                "website": "",
                "city": "",
                "source": "",
                "category": "",
            }

            # custom_fields -> вытаскиваем по id
            for cf in t.get("custom_fields", []):
                fid = str(cf.get("id") or "")
                val = cf.get("value")
                if not fid:
                    continue

                if field_map.get("clinic_name") == fid and val:
                    norm["clinic_name"] = val
                elif field_map.get("email") == fid and val:
                    norm["email"] = val
                elif field_map.get("phone") == fid and val:
                    norm["phone"] = val
                elif field_map.get("website") == fid and val:
                    norm["website"] = val
                elif field_map.get("city") == fid and val:
                    norm["city"] = val
                elif field_map.get("source") == fid and val:
                    norm["source"] = val
                elif field_map.get("category") == fid and val:
                    norm["category"] = val
                elif field_map.get("status") == fid and val:
                    norm["status"] = val

            tasks_out.append(norm)

        return tasks_out

    # ------------------------------------------------------------------
    # СОЗДАНИЕ / ОБНОВЛЕНИЕ ЛИДА
    # ------------------------------------------------------------------
    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> str:
        """
        Создаёт задачу-лид в указанном листе и проставляет кастомные поля.
        Пока делаем "create always", а дедупликацию ты делаешь в leads.py.
        Возвращает task_id.
        """
        name = lead.get("clinic_name") or lead.get("name") or "Clinic"
        status = lead.get("status") or READY_STATUS

        # 1. создаём задачу
        create_url = f"{API_BASE}/list/{list_id}/task"
        payload = {
            "name": name,
            "status": status,
        }
        created = self._post(create_url, json=payload)
        task_id = str(created.get("id") or created.get("task", {}).get("id") or "")
        if not task_id:
            raise RuntimeError("ClickUp: task was not created")

        # 2. проставляем кастомные поля, если они есть
        field_map = self._list_custom_fields_map(list_id)

        def _set_cf(key: str, value: Any):
            fid = field_map.get(key)
            if not fid or value in (None, "", []):
                return
            url = f"{API_BASE}/task/{task_id}/field/{fid}"
            self._post(url, json={"value": value})

        _set_cf("clinic_name", lead.get("clinic_name"))
        _set_cf("email", lead.get("email"))
        _set_cf("phone", lead.get("phone"))
        _set_cf("website", lead.get("website"))
        _set_cf("city", lead.get("city"))
        _set_cf("source", lead.get("source"))
        _set_cf("category", lead.get("category"))
        _set_cf("status", status)

        return task_id

    # ------------------------------------------------------------------
    # ПОИСК ЗАДАЧИ ПО EMAIL (для /replies)
    # ------------------------------------------------------------------
    def find_task_by_email(self, email_val: str) -> Optional[Dict[str, Any]]:
        """
        Очень простой поиск: пробегаемся по всем листам space и ищем задачу,
        у которой кастомное поле email == email_val.
        Для твоего текущего размера базы этого достаточно.
        """
        # сначала получим все листы
        lists_data = self._get(f"{API_BASE}/space/{self.space_id}/list")
        for lst in lists_data.get("lists", []):
            list_id = str(lst["id"])
            field_map = self._list_custom_fields_map(list_id)
            email_fid = field_map.get("email")
            if not email_fid:
                continue

            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                if (t.get("email") or "").lower() == email_val.lower():
                    return {
                        "task_id": t["task_id"],
                        "clinic_name": t.get("clinic_name") or t.get("name") or "",
                        "list_id": list_id,
                    }
        return None

    # ------------------------------------------------------------------
    # ПЕРЕНОС ЛИДА В СТАТУС
    # ------------------------------------------------------------------
    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{API_BASE}/task/{task_id}"
        self._put(url, json={"status": status})


# ----------------------------------------------------------------------
# Синглтон, как у тебя был раньше
# ----------------------------------------------------------------------
clickup_client = ClickUpClient(
    token=settings.CLICKUP_API_TOKEN,
    team_id=settings.CLICKUP_TEAM_ID,
    space_id=settings.CLICKUP_SPACE_ID,
)
