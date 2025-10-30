# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")
logging.basicConfig(level=logging.INFO)

CLICKUP_TOKEN = os.getenv("CLICKUP_API_TOKEN", "").strip()
SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "").strip()
TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "").strip()
TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "").strip()

BASE_URL = "https://api.clickup.com/api/v2"

# наши статусы, которые мы ХОТИМ
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
    def __init__(self, space_id: str, team_id: str) -> None:
        self.space_id = space_id
        self.team_id = team_id

    # ── HTTP ─────────────────────────────────────────────────────────
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

    # ── лист под штат ────────────────────────────────────────────────
    def get_or_create_list_for_state(self, state: str) -> str:
        if not self.space_id:
            raise ClickUpError("CLICKUP_SPACE_ID is empty")

        wanted_name = f"LEADS-{state}"

        # 1. ищем
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            if item.get("name") == wanted_name:
                return str(item["id"])

        # 2. создаём
        create_url = f"{BASE_URL}/space/{self.space_id}/list"
        created = self._post(create_url, {"name": wanted_name})
        list_id = str(created["id"])
        log.info("clickup:created list %s (%s)", list_id, wanted_name)

        # 3. пытаемся скопировать из шаблона (как в самом первом рабочем варианте)
        if TEMPLATE_LIST_ID:
            self._copy_fields_and_statuses_from_template(list_id, TEMPLATE_LIST_ID)
        else:
            log.warning("clickup: no CLICKUP_TEMPLATE_LIST_ID, list stays with default statuses")

        return list_id

    # ── копирование из шаблона ───────────────────────────────────────
    def _copy_fields_and_statuses_from_template(self, target_list_id: str, template_list_id: str) -> None:
        # 1) поля
        try:
            t_fields = self._list_raw_custom_fields(template_list_id)
            for f in t_fields:
                self._ensure_custom_field(target_list_id, f)
        except Exception as e:
            log.warning("clickup: cannot copy custom fields %s -> %s: %s", template_list_id, target_list_id, e)

        # 2) статусы
        try:
            t_info = self._get(f"{BASE_URL}/list/{template_list_id}")
            statuses = t_info.get("statuses") or []
            if statuses:
                # пробуем применить — НО ClickUp может это проигнорировать в этом воркспейсе
                self._put(f"{BASE_URL}/list/{target_list_id}", {"statuses": statuses})
                log.info("clickup: statuses from %s applied to %s", template_list_id, target_list_id)
            else:
                log.warning("clickup: template %s has no statuses", template_list_id)
        except Exception as e:
            # тут мы не падаем — просто лог
            log.warning("clickup: cannot copy statuses %s -> %s: %s", template_list_id, target_list_id, e)

    def _list_raw_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{BASE_URL}/list/{list_id}/field"
        try:
            data = self._get(url)
        except Exception as e:
            log.warning("clickup: list_raw_custom_fields failed for %s: %s", list_id, e)
            return []
        if not isinstance(data, list):
            return []
        return data

    def _ensure_custom_field(self, list_id: str, field_def: Dict[str, Any]) -> None:
        name = field_def.get("name")
        ftype = field_def.get("type")
        if not name or not ftype:
            return
        try:
            resp = self._post(f"{BASE_URL}/list/{list_id}/field", {"name": name, "type": ftype})
            if not isinstance(resp, dict) or not resp.get("id"):
                log.warning("clickup: cannot create field %s on %s (no id)", name, list_id)
        except ClickUpError as e:
            # тут как раз твой случай: "Custom field usages exceeded"
            log.warning("clickup: cannot create field %s on %s: %s", name, list_id, e)

    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for f in self._list_raw_custom_fields(list_id):
            fid = str(f.get("id") or "")
            name = str(f.get("name") or "")
            if fid and name:
                out[name] = fid
        return out

    # ── чтение задач ─────────────────────────────────────────────────
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

        # нормализуем статус и кастомные
        for t in out:
            st = t.get("status")
            if isinstance(st, dict):
                t["status"] = st.get("status") or st.get("value") or ""
            elif isinstance(st, str):
                t["status"] = st
            else:
                t["status"] = ""

            cf = {}
            for fld in (t.get("custom_fields") or []):
                n = fld.get("name")
                v = fld.get("value")
                if n:
                    cf[n] = v
            t["fields"] = cf

        return out

    # ── поиск по email ───────────────────────────────────────────────
    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            list_id = str(item["id"])
            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                fields = t.get("fields") or {}
                cand = (
                    fields.get("Общий адрес электронной почты")
                    or fields.get("Email")
                    or fields.get("email")
                    or ""
                )
                if cand and cand.lower() == email_addr.lower():
                    return {
                        "task_id": t["id"],
                        "clinic_name": t.get("name") or t.get("text") or "",
                    }
        return None

    # ── смена статуса ────────────────────────────────────────────────
    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{BASE_URL}/task/{task_id}"
        self._put(url, {"status": status})

    # ── создание/обновление лида ─────────────────────────────────────
    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> None:
        """
        Главная фишка: создаём задачу БЕЗ status, чтобы не ловить
        `Status not found`, если ClickUp не дал нам статусы из шаблона.
        Потом, если в листе правда есть 'NEW', мы её уже переведём.
        """
        name = lead.get("name") or "Clinic"

        # 1. создаём БЕЗ статуса
        try:
            created = self._post(f"{BASE_URL}/list/{list_id}/task", {"name": name})
        except ClickUpError as e:
            log.error("clickup: cannot create task in list %s: %s", list_id, e)
            return

        task_id = str(created["id"])

        # 2. если у листа реально есть наш NEW — переведём
        try:
            list_info = self._get(f"{BASE_URL}/list/{list_id}")
            statuses = list_info.get("statuses") or []
            has_new = any((s.get("status") or s.get("name")) == NEW_STATUS for s in statuses)
            if has_new:
                # тогда уже можно
                self._put(f"{BASE_URL}/task/{task_id}", {"status": NEW_STATUS})
        except Exception:
            # не критично
            pass

        # 3. кастомные поля
        field_map = self._list_custom_fields_map(list_id)

        def _set_cf(field_name: str, value: Any) -> None:
            fid = field_map.get(field_name)
            if not fid:
                return
            try:
                self._put(f"{BASE_URL}/task/{task_id}/field/{fid}", {"value": value})
            except ClickUpError as e:
                log.warning("clickup: cannot set field %s on task %s: %s", field_name, task_id, e)

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
        if lead.get("address"):
            _set_cf("Общий адрес", lead["address"])
        if lead.get("source"):
            _set_cf("Принадлежность к соцсети / источнику", lead["source"])


# singleton
clickup_client = ClickUpClient(space_id=SPACE_ID, team_id=TEAM_ID)
