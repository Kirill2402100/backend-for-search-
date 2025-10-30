# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")
logging.basicConfig(level=logging.INFO)

CLICKUP_TOKEN = os.getenv("CLICKUP_API_TOKEN", "")
SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "")
TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "")
# этот лист мы используем как "эталон" — в нём правильные русские поля
TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "").strip()

BASE_URL = "https://api.clickup.com/api/v2"

# наши статусы (ими пользуется telegram_bot.py)
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"


def _headers() -> Dict[str, str]:
    return {
        "Authorization": CLICKUP_TOKEN,
        "Content-Type": "application/json",
    }


class ClickUpError(Exception):
    pass


class ClickUpClient:
    def __init__(self, space_id: str, team_id: str):
        self.space_id = space_id
        self.team_id = team_id

    # -------------------------
    # базовые запросы
    # -------------------------
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        r = requests.get(url, headers=_headers(), params=params, timeout=15)
        if r.status_code >= 400:
            raise ClickUpError(f"ClickUp GET error: {r.status_code} {r.text}")
        return r.json()

    def _post(self, url: str, json: Dict[str, Any]) -> Any:
        r = requests.post(url, headers=_headers(), json=json, timeout=15)
        if r.status_code >= 400:
            raise ClickUpError(f"ClickUp POST error: {r.status_code} {r.text}")
        return r.json()

    def _put(self, url: str, json: Dict[str, Any]) -> Any:
        r = requests.put(url, headers=_headers(), json=json, timeout=15)
        if r.status_code >= 400:
            raise ClickUpError(f"ClickUp PUT error: {r.status_code} {r.text}")
        return r.json()

    # -------------------------
    # лист под штат
    # -------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        wanted_name = f"LEADS-{state}"

        # 1. ищем в спейсе
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            if item.get("name") == wanted_name:
                return str(item["id"])

        # 2. создаём
        create_url = f"{BASE_URL}/space/{self.space_id}/list"
        payload = {"name": wanted_name}
        created = self._post(create_url, payload)
        list_id = str(created["id"])
        log.info("clickup: created list %s (%s)", wanted_name, list_id)

        # 3. копируем поля и статусы из эталона
        if TEMPLATE_LIST_ID:
            log.info(
                "clickup: will copy statuses & fields from template %s -> %s",
                TEMPLATE_LIST_ID,
                list_id,
            )
            self._copy_fields_and_statuses_from_template(list_id, TEMPLATE_LIST_ID)
        else:
            log.warning("clickup: CLICKUP_TEMPLATE_LIST_ID is empty -> %s will have default fields", list_id)

        return list_id

    # -------------------------
    # копирование полей и статусов
    # -------------------------
    def _copy_fields_and_statuses_from_template(self, target_list_id: str, template_list_id: str) -> None:
        try:
            # 1. статусы
            t_info = self._get(f"{BASE_URL}/list/{template_list_id}")
            t_statuses = t_info.get("statuses") or []
            if t_statuses:
                self._put(f"{BASE_URL}/list/{target_list_id}", {"statuses": t_statuses})
                log.info("clickup: statuses copied from %s to %s", template_list_id, target_list_id)

            # 2. кастомные поля
            t_fields = self._list_raw_custom_fields(template_list_id)
            for f in t_fields:
                self._ensure_custom_field(target_list_id, f)
        except Exception as e:
            log.warning("clickup: copy from template failed: %s", e)

    def _list_raw_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{BASE_URL}/list/{list_id}/field"
        data = self._get(url)
        return data if isinstance(data, list) else []

    def _ensure_custom_field(self, list_id: str, field_def: Dict[str, Any]) -> None:
        try:
            name = field_def.get("name")
            ftype = field_def.get("type")
            payload = {"name": name, "type": ftype}
            self._post(f"{BASE_URL}/list/{list_id}/field", payload)
        except Exception as e:
            # тут часто бывает лимит / отключены кастомные — просто пишем
            log.warning(
                "clickup: cannot create field %s on list %s (%s): %s",
                field_def.get("name"),
                list_id,
                field_def.get("id"),
                e,
            )

    # -------------------------
    # карта полей
    # -------------------------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        raw = self._list_raw_custom_fields(list_id)
        for f in raw:
            fid = str(f.get("id") or "")
            name = str(f.get("name") or "")
            if fid and name:
                out[name] = fid
        return out

    # -------------------------
    # чтение задач
    # -------------------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{BASE_URL}/list/{list_id}/task"
        params = {"subtasks": "true", "page": 0}
        out: List[Dict[str, Any]] = []

        while True:
            data = self._get(url, params=params)
            tasks = data.get("tasks", [])
            out.extend(tasks)
            if len(tasks) < 100:
                break
            params["page"] += 1

        # распакуем статус и кастомные
        for t in out:
            if isinstance(t.get("status"), dict):
                t["status"] = t.get("status", {}).get("status") or t.get("status", {}).get("value") or ""
            cf = {}
            for fld in (t.get("custom_fields") or []):
                n = fld.get("name")
                v = fld.get("value")
                if n:
                    cf[n] = v
            t["fields"] = cf

        return out

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            list_id = str(item["id"])
            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                fields = t.get("fields") or {}
                mail = (
                    fields.get("Общий адрес электронной почты")
                    or fields.get("Email")
                    or ""
                )
                if mail and mail.lower() == email_addr.lower():
                    return {
                        "task_id": t["id"],
                        "clinic_name": t.get("name") or t.get("text") or "",
                    }
        return None

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        self._put(f"{BASE_URL}/task/{task_id}", {"status": status})

    # -------------------------
    # создание/апдейт лида
    # -------------------------
    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> None:
        name = lead.get("name") or "Clinic"
        status = lead.get("status") or NEW_STATUS

        created = self._post(
            f"{BASE_URL}/list/{list_id}/task",
            {
                "name": name,
                "status": status,
            },
        )
        task_id = created["id"]

        field_map = self._list_custom_fields_map(list_id)

        def _set_cf(fname: str, value: Any) -> None:
            fid = field_map.get(fname)
            if not fid:
                return
            self._put(f"{BASE_URL}/task/{task_id}/field/{fid}", {"value": value})

        # сопоставляем наши поля с русскими в шаблоне
        if lead.get("email"):
            _set_cf("Общий адрес электронной почты", lead["email"])
        if lead.get("phone"):
            _set_cf("Номер телефона", lead["phone"])
        if lead.get("website"):
            _set_cf("URL веб-сайта", lead["website"])
        if lead.get("facebook"):
            _set_cf("URL Facebook", lead["facebook"])
        if lead.get("instagram"):
            _set_cf("URL Instagram", lead["instagram"])
        if lead.get("linkedin"):
            _set_cf("URL LinkedIn", lead["linkedin"])
        if lead.get("twitter"):
            _set_cf("URL Twitter/X", lead["twitter"])
        if lead.get("source"):
            _set_cf("Принадлежность к соцсети / источнику", lead["source"])
        if lead.get("address"):
            _set_cf("Общий адрес", lead["address"])


clickup_client = ClickUpClient(space_id=SPACE_ID, team_id=TEAM_ID)
