# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")
logging.basicConfig(level=logging.INFO)

# ──────────────────────
# ENV
# ──────────────────────
CLICKUP_TOKEN = os.getenv("CLICKUP_API_TOKEN", "").strip()
SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "").strip()
TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "").strip()
# важно: мы сейчас прямо указываем на лист NY как на шаблон
TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "").strip()

BASE_URL = "https://api.clickup.com/api/v2"

# ──────────────────────
# наши статусы
# ──────────────────────
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
    """
    Обёртка вокруг ClickUp:
    - создаём лист под штат (LEADS-NY, LEADS-FL …)
    - при наличии шаблона — копируем ОТТУДА статусы и кастомные поля
    - читаем задачи
    - создаём/обновляем лиды (таски) с нужными КАСТОМНЫМИ полями
    """

    def __init__(self, space_id: str, team_id: str) -> None:
        self.space_id = space_id
        self.team_id = team_id

    # ──────────────────────
    # базовые HTTP
    # ──────────────────────
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

    # ──────────────────────
    # лист под штат
    # ──────────────────────
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Ищем лист LEADS-<STATE> в пространстве.
        Если нет — создаём. Если задан TEMPLATE_LIST_ID — после создания
        попробуем скопировать с него поля и статусы.
        """
        if not self.space_id:
            raise ClickUpError("CLICKUP_SPACE_ID is empty")

        wanted_name = f"LEADS-{state}"

        # 1) ищем в space
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            if item.get("name") == wanted_name:
                list_id = str(item["id"])
                # на всякий случай можно было бы тут тоже дотянуть статусы из шаблона,
                # но не будем трогать уже существующие
                return list_id

        # 2) создаём
        create_url = f"{BASE_URL}/space/{self.space_id}/list"
        payload: Dict[str, Any] = {"name": wanted_name}
        created = self._post(create_url, payload)
        list_id = str(created["id"])
        log.info("clickup:created list %s (%s)", list_id, wanted_name)

        # 3) если есть шаблон — копируем
        if TEMPLATE_LIST_ID:
            log.info(
                "clickup: will copy statuses & fields from template %s -> %s",
                TEMPLATE_LIST_ID,
                list_id,
            )
            self._copy_fields_and_statuses_from_template(list_id, TEMPLATE_LIST_ID)
        else:
            log.warning("clickup: CLICKUP_TEMPLATE_LIST_ID is empty -> list %s will have default fields", list_id)

        return list_id

    # ──────────────────────
    # копирование из шаблона
    # ──────────────────────
    def _copy_fields_and_statuses_from_template(self, target_list_id: str, template_list_id: str) -> None:
        """
        ClickUp не умеет «клонировать лист» по API, поэтому делаем best-effort:
        1. читаем кастомные поля у шаблона
        2. создаём такие же у целевого
        3. читаем статусы у шаблона
        4. проставляем их у целевого
        Если где-то получим странный ответ — просто залогируем.
        """
        # 1) поля
        try:
            t_fields = self._list_raw_custom_fields(template_list_id)
            for f in t_fields:
                self._ensure_custom_field(target_list_id, f)
        except Exception as e:
            log.warning("clickup: cannot copy custom fields from %s to %s: %s", template_list_id, target_list_id, e)

        # 2) статусы
        try:
            template_info = self._get(f"{BASE_URL}/list/{template_list_id}")
            statuses = template_info.get("statuses") or []
            if statuses:
                self._put(f"{BASE_URL}/list/{target_list_id}", {"statuses": statuses})
        except Exception as e:
            log.warning("clickup: cannot copy statuses from %s to %s: %s", template_list_id, target_list_id, e)

    def _list_raw_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Возвращает «какие кастомные поля тут вообще есть».
        ClickUp иногда возвращает не список — тогда вернём []
        """
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
        """
        Создаём в list_id поле того же name и type, что в шаблоне.
        В дешёвых/фри планах ClickUp иногда просто возвращает {} или
        ошибку «Custom field usages exceeded» — в таком случае
        мы не валимся, просто пишем в лог и идём дальше.
        """
        name = field_def.get("name")
        ftype = field_def.get("type")
        if not name or not ftype:
            return

        payload = {
            "name": name,
            "type": ftype,
        }
        try:
            resp = self._post(f"{BASE_URL}/list/{list_id}/field", payload)
            if not isinstance(resp, dict) or not resp.get("id"):
                log.warning("clickup: cannot create custom field '%s' on %s (no id in resp)", name, list_id)
        except ClickUpError as e:
            # лимит полей или что-то такое — не ломаемся
            log.warning("clickup: cannot create custom field '%s' on %s: %s", name, list_id, e)

    # ──────────────────────
    # карта полей этого листа
    # ──────────────────────
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        """
        Вернём {имя_поля: id_поля} для дальнейших апдейтов.
        """
        out: Dict[str, str] = {}
        raw = self._list_raw_custom_fields(list_id)
        for f in raw:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id") or "")
            name = str(f.get("name") or "")
            if fid and name:
                out[name] = fid
        return out

    # ──────────────────────
    # чтение лидов
    # ──────────────────────
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Забираем ВСЕ задачи из листа, со всех страниц.
        """
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

        # обогатим задачки удобными полями
        field_map = self._list_custom_fields_map(list_id)
        for t in out:
            # нормализуем статус
            st = t.get("status")
            if isinstance(st, dict):
                t["status"] = st.get("status") or st.get("value") or ""
            elif isinstance(st, str):
                t["status"] = st
            else:
                t["status"] = ""

            # кастомные — в “fields”
            cf = {}
            for fld in (t.get("custom_fields") or []):
                name = fld.get("name")
                val = fld.get("value")
                if name:
                    cf[name] = val
            t["fields"] = cf

        return out

    # ──────────────────────
    # поиск по email
    # ──────────────────────
    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Идём по всем листам в SPACE и ищем задачу, где в кастомных полях
        лежит этот email. Поддерживаем и твоё русское имя поля, и короткое 'Email'.
        """
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

    # ──────────────────────
    # смена статуса
    # ──────────────────────
    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{BASE_URL}/task/{task_id}"
        self._put(url, {"status": status})

    # ──────────────────────
    # создание/обновление лида
    # ──────────────────────
    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> None:
        """
        Пока что простейшая логика: создаём задачу и потом докидываем кастомные поля.
        Дедупликация и «обновить если есть» у тебя сейчас делается уровнем выше.
        """
        name = lead.get("name") or "Clinic"
        status = lead.get("status") or NEW_STATUS

        payload: Dict[str, Any] = {
            "name": name,
            "status": status,
        }

        created = self._post(f"{BASE_URL}/list/{list_id}/task", payload)
        task_id = str(created["id"])

        # проставляем кастомные поля — но ТОЛЬКО те, что уже есть в листе (из шаблона)
        field_map = self._list_custom_fields_map(list_id)

        def _set_cf(field_name: str, value: Any) -> None:
            fid = field_map.get(field_name)
            if not fid:
                return
            self._put(
                f"{BASE_URL}/task/{task_id}/field/{fid}",
                {"value": value},
            )

        # маппинг из lead -> твои русские поля из NY
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
