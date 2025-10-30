# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")

CLICKUP_BASE = "https://api.clickup.com/api/v2"

CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "")
CLICKUP_SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "")
CLICKUP_TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "")
# он у нас есть в env, но мы его БОЛЬШЕ НЕ ИСПОЛЬЗУЕМ специально
CLICKUP_TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "")

# ===== наши статусы =====
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
REPLIED_STATUS = "REPLIED"
INVALID_STATUS = "INVALID"

# ===== нужные кастомные поля (если получится) =====
REQUIRED_CUSTOM_FIELDS = {
    "Email": {"type": "text"},
    "Website": {"type": "text"},
    "Facebook": {"type": "text"},
    "Instagram": {"type": "text"},
    "LinkedIn": {"type": "text"},
}


class ClickUpError(Exception):
    pass


class ClickUpClient:
    def __init__(self) -> None:
        if not CLICKUP_API_TOKEN:
            raise RuntimeError("CLICKUP_API_TOKEN is not set")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": CLICKUP_API_TOKEN})

    # ---------------- low level ----------------

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = self.session.get(url, params=params, timeout=25)
        if r.status_code >= 300:
            raise ClickUpError(f"GET {url} -> {r.status_code} {r.text}")
        return r.json()

    def _post(self, url: str, json: Dict[str, Any]) -> Dict[str, Any]:
        r = self.session.post(url, json=json, timeout=25)
        if r.status_code >= 300:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")
        return r.json()

    def _put(self, url: str, json: Dict[str, Any]) -> Dict[str, Any]:
        r = self.session.put(url, json=json, timeout=25)
        if r.status_code >= 300:
            raise ClickUpError(f"PUT {url} -> {r.status_code} {r.text}")
        return r.json()

    # ---------------- lists ----------------

    def _list_lists_in_space(self) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_BASE}/space/{CLICKUP_SPACE_ID}/list"
        data = self._get(url)
        return data.get("lists", [])

    def _set_pipeline(self, list_id: str) -> None:
        """
        Ставим наш набор статусов через корректный эндпоинт.
        """
        url = f"{CLICKUP_BASE}/list/{list_id}"
        payload = {
            "statuses": [
                {"status": NEW_STATUS,     "type": "open",   "orderindex": 0, "color": "#4b7bec"},
                {"status": READY_STATUS,   "type": "open",   "orderindex": 1, "color": "#8854d0"},
                {"status": SENT_STATUS,    "type": "open",   "orderindex": 2, "color": "#20bf6b"},
                {"status": REPLIED_STATUS, "type": "closed", "orderindex": 3, "color": "#0fb9b1"},
                {"status": INVALID_STATUS, "type": "closed", "orderindex": 4, "color": "#eb3b5a"},
            ]
        }
        try:
            self._put(url, payload)
            log.info("clickup:set pipeline for list %s", list_id)
        except ClickUpError as e:
            # если в спейсе запрещено менять статусы — будет просто варнинг
            log.warning("clickup:cannot set pipeline on list %s: %s", list_id, e)

    def _list_custom_fields(self, list_id: str) -> Dict[str, str]:
        url = f"{CLICKUP_BASE}/list/{list_id}/field"
        data = self._get(url)
        out: Dict[str, str] = {}
        for f in data.get("fields", []):
            name = f.get("name")
            fid = f.get("id")
            if name and fid:
                out[name] = fid
        return out

    def _create_field_on_list(self, list_id: str, name: str, ftype: str) -> Optional[str]:
        """
        Пробуем создать кастомное поле. Если план не даёт — вернём None.
        """
        url = f"{CLICKUP_BASE}/list/{list_id}/field"
        payload = {"type": ftype, "name": name, "required": False}
        try:
            resp = self._post(url, payload)
        except ClickUpError as e:
            # это как раз твой случай: FIELD_033 → план не даёт
            log.warning("clickup:cannot create field %s on list %s (%s)", name, list_id, e)
            return None

        fid = resp.get("id")
        if not fid:
            # бывает 200 без id — перечитаем
            fields_after = self._list_custom_fields(list_id)
            fid = fields_after.get(name)
            if not fid:
                log.warning("clickup:cannot create field %s on list %s (no id in resp)", name, list_id)
                return None
        return fid

    def _ensure_required_fields(self, list_id: str) -> Dict[str, Optional[str]]:
        """
        Создаём нужные поля, НО если план не даёт — вернём словарь с None.
        """
        try:
            existing = self._list_custom_fields(list_id)
        except ClickUpError as e:
            log.warning("clickup:cannot list fields on %s: %s", list_id, e)
            return {name: None for name in REQUIRED_CUSTOM_FIELDS.keys()}

        result: Dict[str, Optional[str]] = {}

        for fname, cfg in REQUIRED_CUSTOM_FIELDS.items():
            if fname in existing:
                result[fname] = existing[fname]
            else:
                fid = self._create_field_on_list(list_id, fname, cfg["type"])
                result[fname] = fid
        return result

    def get_or_create_list_for_state(self, state: str) -> str:
        """
        ВАЖНО: больше НЕ создаём из шаблона.
        Потому что шаблон тащит русские статусы, и ClickUp не даёт их перезаписать.
        """
        state = state.upper()
        target_name = f"LEADS-{state}"

        # 1. ищем уже существующий
        for lst in self._list_lists_in_space():
            if lst.get("name") == target_name:
                return lst["id"]

        # 2. создаём пустой лист в спейсе
        url = f"{CLICKUP_BASE}/space/{CLICKUP_SPACE_ID}/list"
        payload = {"name": target_name, "content": ""}
        resp = self._post(url, payload)
        new_id = resp["id"]
        log.info("clickup:created list %s (%s)", new_id, target_name)

        # 3. ставим наш pipeline
        self._set_pipeline(new_id)

        # 4. пробуем создать поля, но если не получилось — работаем дальше без них
        self._ensure_required_fields(new_id)

        return new_id

    # ---------------- tasks ----------------

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_BASE}/list/{list_id}/task"
        data = self._get(url, params={"subtasks": "true"})
        return data.get("tasks", [])

    def create_task(
        self,
        list_id: str,
        name: str,
        description: str = "",
        status: str = NEW_STATUS,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        1) пробуем создать с нашим статусом и полями
        2) если "Status not found" → сразу без статуса и без полей
        3) если "FIELD_033" → без полей (и без статуса, чтобы ещё раз не поймать гонку)
        """
        url = f"{CLICKUP_BASE}/list/{list_id}/task"

        def _base_payload() -> Dict[str, Any]:
            p: Dict[str, Any] = {"name": name}
            if description:
                p["description"] = description
            return p

        # --- 1. первая попытка: как хотим ---
        payload = _base_payload()
        payload["status"] = status
        if custom_fields:
            cf_list: List[Dict[str, Any]] = []
            for fid, val in custom_fields.items():
                if fid:
                    cf_list.append({"id": fid, "value": val})
            if cf_list:
                payload["custom_fields"] = cf_list

        try:
            resp = self._post(url, payload)
            task_id = resp.get("id")
            if task_id:
                log.info("clickup:created lead task %s on list %s (%s)", task_id, list_id, name)
            return task_id
        except ClickUpError as e:
            txt = str(e)

            # --- 2. статус ещё не применился на листе ---
            if "Status not found" in txt or "CRTSK_001" in txt:
                log.warning(
                    "clickup:create task on list %s failed (status not found) -> retrying without status & fields",
                    list_id,
                )
                payload2 = _base_payload()
                # без статуса и БЕЗ кастомных полей
                resp = self._post(url, payload2)
                return resp.get("id")

            # --- 3. лимит по кастомным полям ---
            if "FIELD_033" in txt:
                log.warning(
                    "clickup:custom field limit on list %s -> creating task without custom fields",
                    list_id,
                )
                payload3 = _base_payload()
                # и без статуса — чтобы не словить ту же гонку
                resp = self._post(url, payload3)
                return resp.get("id")

            # другое — пусть валится
            raise

    def update_task_status(self, task_id: str, status: str) -> None:
        url = f"{CLICKUP_BASE}/task/{task_id}"
        self._put(url, {"status": status})

    # ---------------- higher level ----------------

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> bool:
        clinic_name = (lead.get("clinic_name") or "").strip()
        if not clinic_name:
            return False

        # дедуп по названию
        tasks = self.get_leads_from_list(list_id)
        for t in tasks:
            if (t.get("name") or "").strip().lower() == clinic_name.lower():
                return False

        # пробуем получить id полей, но если ничего не вышло — просто не будем их слать
        field_ids = self._ensure_required_fields(list_id)

        if not any(field_ids.values()):
            # вообще нет полей → создаём без них
            self.create_task(
                list_id=list_id,
                name=clinic_name,
                description=lead.get("address") or "",
                status=NEW_STATUS,
                custom_fields=None,
            )
            return True

        custom_values = {
            field_ids.get("Email"): lead.get("email") or "",
            field_ids.get("Website"): lead.get("website") or "",
            field_ids.get("Facebook"): lead.get("facebook") or "",
            field_ids.get("Instagram"): lead.get("instagram") or "",
            field_ids.get("LinkedIn"): lead.get("linkedin") or "",
        }

        self.create_task(
            list_id=list_id,
            name=clinic_name,
            description=lead.get("address") or "",
            status=NEW_STATUS,
            custom_fields=custom_values,
        )
        return True

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        self.update_task_status(task_id, status)

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        lists = self._list_lists_in_space()
        for lst in lists:
            lid = lst.get("id")
            if not lid:
                continue
            tasks = self.get_leads_from_list(lid)
            fields_map = self._list_custom_fields(lid)
            email_field_id = fields_map.get("Email")
            if not email_field_id:
                continue
            for t in tasks:
                for cf in t.get("custom_fields", []):
                    if (
                        cf.get("id") == email_field_id
                        and (cf.get("value") or "").lower() == email_addr.lower()
                    ):
                        return {
                            "task_id": t["id"],
                            "clinic_name": t.get("name") or "",
                            "list_id": lid,
                        }
        return None


clickup_client = ClickUpClient()
