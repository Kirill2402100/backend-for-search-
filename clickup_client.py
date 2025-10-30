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
# важное: это id ЛИСТА-ШАБЛОНА (у тебя сейчас это NY)
CLICKUP_TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "")

# ===== статусы =====
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
REPLIED_STATUS = "REPLIED"      # ← вернули, чтобы telegram_bot.py не падал
INVALID_STATUS = "INVALID"

# какие кастомные поля нам нужны
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

    # ------------- low level -------------

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

    # ------------- lists -------------

    def _list_lists_in_space(self) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_BASE}/space/{CLICKUP_SPACE_ID}/list"
        data = self._get(url)
        return data.get("lists", [])

    def _set_pipeline_like_ny(self, list_id: str) -> None:
        """
        Даже если лист создавался из шаблона — навешиваем свои статусы.
        Делаем 5 штук: NEW, READY, SENT, REPLIED, INVALID.
        """
        url = f"{CLICKUP_BASE}/list/{list_id}/field"
        payload = {
            "statuses": [
                {
                    "status": NEW_STATUS,
                    "type": "open",
                    "orderindex": 0,
                    "color": "#4b7bec",
                },
                {
                    "status": READY_STATUS,
                    "type": "open",
                    "orderindex": 1,
                    "color": "#8854d0",
                },
                {
                    "status": SENT_STATUS,
                    "type": "open",
                    "orderindex": 2,
                    "color": "#20bf6b",
                },
                {
                    "status": REPLIED_STATUS,
                    "type": "closed",
                    "orderindex": 3,
                    "color": "#0fb9b1",
                },
                {
                    "status": INVALID_STATUS,
                    "type": "closed",
                    "orderindex": 4,
                    "color": "#eb3b5a",
                },
            ]
        }
        try:
            self._post(url, payload)
            log.info("clickup:set pipeline for list %s", list_id)
        except ClickUpError as e:
            # бывает, что у ClickUp на списке стоят “зафиксированные” статусы — тогда просто логируем
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
        Создаём кастомное поле. Если ClickUp не вернул id (как в твоём логе),
        пробуем перечитать список полей и взять по имени.
        """
        url = f"{CLICKUP_BASE}/list/{list_id}/field"
        payload = {
            "type": ftype,
            "name": name,
            "required": False,
        }
        try:
            resp = self._post(url, payload)
        except ClickUpError as e:
            # лимит по кастомным полям — просто логируем и идём дальше
            log.warning("clickup:cannot create field %s on list %s (%s)", name, list_id, e)
            return None

        fid = resp.get("id")
        if not fid:
            # иногда API вернул 200, но без id — перечитаем поля и возьмём свежий
            fields_after = self._list_custom_fields(list_id)
            fid = fields_after.get(name)
            if not fid:
                log.warning("clickup:cannot create field %s on list %s (no id in resp)", name, list_id)
                return None
        return fid

    def _ensure_required_fields(self, list_id: str) -> Dict[str, Optional[str]]:
        """
        Проверяем/создаём 5 наших полей. Если не дали создать — значение будет None.
        """
        existing = self._list_custom_fields(list_id)
        result: Dict[str, Optional[str]] = {}

        for fname, cfg in REQUIRED_CUSTOM_FIELDS.items():
            if fname in existing:
                result[fname] = existing[fname]
            else:
                fid = self._create_field_on_list(list_id, fname, cfg["type"])
                result[fname] = fid
        return result

    def get_or_create_list_for_state(self, state: str) -> str:
        state = state.upper()
        target_name = f"LEADS-{state}"

        # 1. пробуем найти уже существующий
        for lst in self._list_lists_in_space():
            if lst.get("name") == target_name:
                return lst["id"]

        # 2. пробуем создать из шаблона (NY)
        if CLICKUP_TEMPLATE_LIST_ID:
            url = f"{CLICKUP_BASE}/space/{CLICKUP_SPACE_ID}/list"
            payload = {
                "name": target_name,
                "content": "",
                "template_id": CLICKUP_TEMPLATE_LIST_ID,
            }
            resp = self._post(url, payload)
            new_id = resp["id"]
            log.info(
                "clickup:created list %s from template %s (%s)",
                new_id,
                CLICKUP_TEMPLATE_LIST_ID,
                target_name,
            )

            # 👇 добавили: ClickUp может НЕ перенести статусы из шаблона
            self._set_pipeline_like_ny(new_id)

            # на всякий случай убедимся, что поля есть
            self._ensure_required_fields(new_id)
            return new_id

        # 3. если шаблона нет/не сработал — создаём пустой и ставим наш pipeline
        url = f"{CLICKUP_BASE}/space/{CLICKUP_SPACE_ID}/list"
        payload = {"name": target_name, "content": ""}
        resp = self._post(url, payload)
        new_id = resp["id"]
        log.info("clickup:created list %s (%s)", new_id, target_name)

        self._set_pipeline_like_ny(new_id)
        self._ensure_required_fields(new_id)

        return new_id

    # ------------- tasks -------------

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
        url = f"{CLICKUP_BASE}/list/{list_id}/task"
        payload: Dict[str, Any] = {
            "name": name,
            "status": status,
        }
        if description:
            payload["description"] = description

        cf_list: List[Dict[str, Any]] = []
        if custom_fields:
            for fid, val in custom_fields.items():
                if fid:  # может быть None, если поле не создалось
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
            # если это лимит по кастомным полям — шлём без них
            if "FIELD_033" in str(e):
                log.warning(
                    "clickup:ClickUp custom field limit reached on list %s -> creating task without custom fields",
                    list_id,
                )
                payload.pop("custom_fields", None)
                resp = self._post(url, payload)
                return resp.get("id")
            raise

    def update_task_status(self, task_id: str, status: str) -> None:
        url = f"{CLICKUP_BASE}/task/{task_id}"
        self._put(url, {"status": status})

    # ------------- higher level -------------

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> bool:
        clinic_name = (lead.get("clinic_name") or "").strip()
        if not clinic_name:
            return False

        # дедуп по названию
        tasks = self.get_leads_from_list(list_id)
        for t in tasks:
            if (t.get("name") or "").strip().lower() == clinic_name.lower():
                return False

        # id полей (или None, если не дали создать)
        field_ids = self._ensure_required_fields(list_id)

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
        # берём все листы спейса
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
