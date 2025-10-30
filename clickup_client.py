# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")
logging.basicConfig(level=logging.INFO)

BASE_URL = "https://api.clickup.com/api/v2"

CLICKUP_TOKEN = os.getenv("CLICKUP_API_TOKEN", "")
SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "")
TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "")
# Лист-эталон (у тебя это был NY)
TEMPLATE_LIST_ID = (os.getenv("CLICKUP_TEMPLATE_LIST_ID", "") or "").strip()

# наши статусы
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"

# если вдруг в ответе 400 "custom field usages exceeded" – просто запомним и не будем долбиться дальше
CF_HARD_FAILED: Dict[str, bool] = {}


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

    # --------------------------------
    # low-level
    # --------------------------------
    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        r = requests.get(url, headers=_headers(), params=params, timeout=15)
        if r.status_code >= 400:
            raise ClickUpError(f"GET {url} -> {r.status_code} {r.text}")
        return r.json()

    def _post(self, url: str, json: Dict[str, Any]) -> Any:
        r = requests.post(url, headers=_headers(), json=json, timeout=15)
        if r.status_code >= 400:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")
        return r.json()

    def _put(self, url: str, json: Dict[str, Any]) -> Any:
        r = requests.put(url, headers=_headers(), json=json, timeout=15)
        if r.status_code >= 400:
            raise ClickUpError(f"PUT {url} -> {r.status_code} {r.text}")
        return r.json()

    # --------------------------------
    # lists
    # --------------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        В НОВОМ space (который ты укажешь в CLICKUP_SPACE_ID) создаём LEADS-<STATE>.
        Если есть — используем.
        После создания пытаемся:
         1) скопировать из TEMPLATE_LIST_ID
         2) если не вышло — заливаем наши английские статусы и 5 англ. полей
        """
        wanted_name = f"LEADS-{state}"

        lists_url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(lists_url)

        for item in data.get("lists", []):
            if item.get("name") == wanted_name:
                return str(item["id"])

        # нет — создаём
        created = self._post(lists_url, {"name": wanted_name})
        list_id = str(created["id"])
        log.info("clickup: created list %s (%s)", wanted_name, list_id)

        # инициализация листа
        self._init_list_from_template_or_default(list_id)

        return list_id

    def _init_list_from_template_or_default(self, list_id: str) -> None:
        # 1. пробуем скопировать из шаблона (твой NY)
        if TEMPLATE_LIST_ID:
            try:
                log.info(
                    "clickup: will copy statuses & fields from template %s -> %s",
                    TEMPLATE_LIST_ID,
                    list_id,
                )
                self._copy_fields_and_statuses_from_template(list_id, TEMPLATE_LIST_ID)
                return
            except Exception as e:
                log.warning("clickup: copy from template failed: %s", e)

        # 2. если не вышло — ставим наши статусы и поля
        log.warning(
            "clickup: using default statuses/fields for list %s (template missing or failed)",
            list_id,
        )
        self._apply_default_statuses(list_id)
        self._ensure_eng_custom_fields(list_id)

    def _copy_fields_and_statuses_from_template(self, target_list_id: str, template_list_id: str) -> None:
        # поля
        t_fields = self._list_raw_custom_fields(template_list_id)
        for f in t_fields:
            self._ensure_custom_field(target_list_id, f)

        # статусы
        t_def = self._get(f"{BASE_URL}/list/{template_list_id}")
        statuses = t_def.get("statuses") or []
        if statuses:
            self._put(f"{BASE_URL}/list/{target_list_id}", {"statuses": statuses})
        else:
            # если шаблон был пустой по статусам — наш дефолт
            self._apply_default_statuses(target_list_id)

    def _apply_default_statuses(self, list_id: str) -> None:
        """
        Прописать листу наши 5 английских статусов.
        """
        payload = {
            "statuses": [
                {"status": NEW_STATUS, "orderindex": 0, "color": "#6f6f6f"},
                {"status": READY_STATUS, "orderindex": 1, "color": "#956fff"},
                {"status": SENT_STATUS, "orderindex": 2, "color": "#2f97ff"},
                {"status": INVALID_STATUS, "orderindex": 3, "color": "#ff5f5f"},
                {"status": REPLIED_STATUS, "orderindex": 4, "color": "#29b47d"},
            ]
        }
        try:
            self._put(f"{BASE_URL}/list/{list_id}", payload)
            log.info("clickup: applied default statuses to list %s", list_id)
        except Exception as e:
            log.warning("clickup: cannot apply default statuses to %s: %s", list_id, e)

    # --------------------------------
    # fields
    # --------------------------------
    def _list_raw_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{BASE_URL}/list/{list_id}/field"
        data = self._get(url)
        return data if isinstance(data, list) else []

    def _ensure_custom_field(self, list_id: str, field_def: Dict[str, Any]) -> None:
        # best effort
        if CF_HARD_FAILED.get(list_id):
            return
        try:
            payload = {
                "name": field_def.get("name"),
                "type": field_def.get("type"),
            }
            resp = self._post(f"{BASE_URL}/list/{list_id}/field", payload)
            if not resp or not resp.get("id"):
                log.warning("clickup: cannot create field %s on list %s (no id in resp)", payload["name"], list_id)
        except ClickUpError as e:
            # лимит — запомним
            if "Custom field usages exceeded" in str(e):
                CF_HARD_FAILED[list_id] = True
            log.warning("clickup: cannot create field on %s: %s", list_id, e)
        except Exception as e:
            log.warning("clickup: cannot create field on %s: %s", list_id, e)

    def _ensure_eng_custom_fields(self, list_id: str) -> None:
        wanted = [
            ("Email", 1),
            ("Website", 1),
            ("Facebook", 1),
            ("Instagram", 1),
            ("LinkedIn", 1),
        ]
        existing = {f.get("name") for f in self._list_raw_custom_fields(list_id)}
        for name, ftype in wanted:
            if name in existing:
                continue
            self._ensure_custom_field(list_id, {"name": name, "type": ftype})

    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        res: Dict[str, str] = {}
        for f in self._list_raw_custom_fields(list_id):
            fid = str(f.get("id") or "")
            name = f.get("name") or ""
            if fid and name:
                res[name] = fid
        return res

    # --------------------------------
    # tasks
    # --------------------------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{BASE_URL}/list/{list_id}/task"
        page = 0
        out: List[Dict[str, Any]] = []
        while True:
            data = self._get(url, params={"page": page, "subtasks": "true"})
            tasks = data.get("tasks", [])
            out.extend(tasks)
            if len(tasks) < 100:
                break
            page += 1
        return out

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> None:
        # главное – имя
        name = (
            lead.get("name")
            or lead.get("title")
            or lead.get("clinic_name")
            or lead.get("business_name")
            or "Clinic"
        )

        # пытаемся создать со статусом NEW
        payload = {
            "name": name,
            "status": NEW_STATUS,
        }

        try:
            created = self._post(f"{BASE_URL}/list/{list_id}/task", payload)
        except ClickUpError as e:
            # если у листа опять “Status not found” – попробуем без статуса
            if "Status not found" in str(e):
                created = self._post(f"{BASE_URL}/list/{list_id}/task", {"name": name})
            else:
                raise

        task_id = str(created["id"])

        # если у нас есть карта полей – проставим
        field_map = self._list_custom_fields_map(list_id)

        def _set_cf(fname: str, value: Any) -> None:
            if not value:
                return
            fid = field_map.get(fname)
            if not fid:
                return
            try:
                self._put(f"{BASE_URL}/task/{task_id}/field/{fid}", {"value": value})
            except Exception as e:
                log.warning("clickup: cannot set field %s on task %s: %s", fname, task_id, e)

        _set_cf("Email", lead.get("email"))
        _set_cf("Website", lead.get("website"))
        _set_cf("Facebook", lead.get("facebook"))
        _set_cf("Instagram", lead.get("instagram"))
        _set_cf("LinkedIn", lead.get("linkedin"))

    # --------------------------------
    # replies (нужно твоему боту)
    # --------------------------------
    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        # берём все листы в space и ищем
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            list_id = str(item["id"])
            tasks = self.get_leads_from_list(list_id)
            field_map = self._list_custom_fields_map(list_id)
            email_field_id = None
            # ищем id поля Email
            for name, fid in field_map.items():
                if name.lower() == "email":
                    email_field_id = fid
                    break
            for t in tasks:
                for cf in t.get("custom_fields") or []:
                    if email_field_id and cf.get("id") == email_field_id:
                        val = cf.get("value") or ""
                        if val.lower() == email_addr.lower():
                            return {
                                "task_id": t["id"],
                                "clinic_name": t.get("name") or "",
                            }
        return None

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        try:
            self._put(f"{BASE_URL}/task/{task_id}", {"status": status})
        except Exception as e:
            log.warning("clickup: cannot move task %s to %s: %s", task_id, status, e)


clickup_client = ClickUpClient(space_id=SPACE_ID, team_id=TEAM_ID)
