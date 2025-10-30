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
# вот эта — теперь ОПЦИОНАЛЬНАЯ
TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "").strip()

BASE_URL = "https://api.clickup.com/api/v2"

# наши статусы
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
    Обёртка вокруг ClickUp. Здесь делаем:
    - создание листа под штат (LEADS-NY и т.п.)
    - чтение/создание кастомных полей
    - создание/обновление задач (лидов)
    """

    def __init__(self, space_id: str, team_id: str):
        self.space_id = space_id
        self.team_id = team_id

    # ---------------------------
    # ВСПОМОГАТЕЛЬНОЕ
    # ---------------------------
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

    # ---------------------------
    # ЛИСТ ПОД ШТАТ
    # ---------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Ищем лист с именем LEADS-<STATE>.
        Если нет — создаём. Если указан TEMPLATE_LIST_ID — создаём из него.
        """
        wanted_name = f"LEADS-{state}"

        # 1. посмотреть все листы в спейсе
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            if item.get("name") == wanted_name:
                return str(item["id"])

        # 2. создавать
        create_url = f"{BASE_URL}/space/{self.space_id}/list"
        payload: Dict[str, Any] = {
            "name": wanted_name,
        }

        # если есть шаблон — укажем его
        if TEMPLATE_LIST_ID:
            # это не строгий “создать из шаблона” endpoint, но мы можем
            # сразу после создания перетащить статусы/поля, поэтому просто создаём пустой
            log.info("clickup: will create list %s and then copy from template %s", wanted_name, TEMPLATE_LIST_ID)

        created = self._post(create_url, payload)
        list_id = str(created["id"])

        # скопировать статусы/поля, если есть шаблон
        if TEMPLATE_LIST_ID:
            self._copy_fields_and_statuses_from_template(list_id, TEMPLATE_LIST_ID)
        else:
            log.warning("clickup: CLICKUP_TEMPLATE_LIST_ID is empty -> list %s will have default fields", list_id)

        return list_id

    # ---------------------------
    # КОПИРОВАНИЕ ПОЛЕЙ/СТАТУСОВ
    # ---------------------------
    def _copy_fields_and_statuses_from_template(self, target_list_id: str, template_list_id: str) -> None:
        """
        В ClickUp нет простого “склонировать лист” по API, поэтому делаем так:
        - читаем кастомные поля из шаблона
        - читаем статусы из шаблона
        - создаём такие же кастомные поля и статусы в целевом листе
        Если что-то не вышло — просто логируем и продолжаем.
        """
        try:
            # кастомные поля
            t_fields = self._list_raw_custom_fields(template_list_id)

            for f in t_fields:
                self._ensure_custom_field(target_list_id, f)

            # статусы
            t_statuses = self._get(f"{BASE_URL}/list/{template_list_id}")
            statuses = t_statuses.get("statuses") or []
            if statuses:
                self._put(
                    f"{BASE_URL}/list/{target_list_id}",
                    {"statuses": statuses},
                )
        except Exception as e:
            log.warning("clickup: copy from template failed: %s", e)

    def _list_raw_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        # официальный endpoint “Get Accessible Custom Fields”:
        url = f"{BASE_URL}/list/{list_id}/field"
        data = self._get(url)
        return data if isinstance(data, list) else []

    def _ensure_custom_field(self, list_id: str, field_def: Dict[str, Any]) -> None:
        """
        Создаём в list_id поле такого же типа/названия, как в шаблоне.
        API у ClickUp не супергладкое, поэтому делаем “best effort”.
        """
        try:
            name = field_def.get("name")
            ftype = field_def.get("type")
            # нельзя просто передать весь объект — поэтому берём минимально
            payload = {
                "name": name,
                "type": ftype,
            }
            self._post(f"{BASE_URL}/list/{list_id}/field", payload)
        except Exception as e:
            log.warning("clickup: cannot create custom field on %s: %s", list_id, e)

    # ---------------------------
    # КАРТА ПОЛЕЙ В ЛИСТЕ
    # ---------------------------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        """
        Вернём словарь {имя_поля: id_поля} для дальнейших апдейтов.
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

    # ---------------------------
    # ЛИДЫ/ЗАДАЧИ
    # ---------------------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Забираем ВСЕ задачи из листа.
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
            t["status"] = (t.get("status") or {}).get("status", "")
            # кастомные — в “fields”
            cf = {}
            for fld in (t.get("custom_fields") or []):
                name = fld.get("name")
                val = fld.get("value")
                if name:
                    cf[name] = val
            t["fields"] = cf

        return out

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Поиск задачи по email в КАСТОМНОМ поле “Общий адрес электронной почты” (как в твоём листе).
        Если назовёшь поле по-другому — поправим тут.
        """
        # проходим по всем листам? сейчас — нет, только по space/list’ам которые мы сами создаём.
        # для простоты — бежим по space и ищем в листах, которые начинаются на LEADS-
        url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(url)
        for item in data.get("lists", []):
            list_id = str(item["id"])
            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                fields = t.get("fields") or {}
                if not fields:
                    continue
                mail = fields.get("Общий адрес электронной почты") or fields.get("Email") or ""
                if mail and mail.lower() == email_addr.lower():
                    return {
                        "task_id": t["id"],
                        "clinic_name": t.get("name") or t.get("text") or "",
                    }
        return None

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{BASE_URL}/task/{task_id}"
        self._put(url, {"status": status})

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> None:
        """
        Создаём или обновляем лид по какому-то ключу.
        Пока что делаем просто: создаём новую задачу.
        Ключ можно будет сделать по “place_id” или по “название+телефон”.
        """
        name = lead.get("name") or "Clinic"
        status = lead.get("status") or READY_STATUS

        payload: Dict[str, Any] = {
            "name": name,
            "status": status,
        }

        # сначала создаём таску
        created = self._post(f"{BASE_URL}/list/{list_id}/task", payload)
        task_id = created["id"]

        # теперь расставим кастомные поля, если они есть
        field_map = self._list_custom_fields_map(list_id)

        def _set_cf(field_name: str, value: Any) -> None:
            fid = field_map.get(field_name)
            if not fid:
                return
            self._put(
                f"{BASE_URL}/task/{task_id}/field/{fid}",
                {"value": value},
            )

        # маппинг наших полей -> в твой лист
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

        # можно положить исходник
        if lead.get("source"):
            _set_cf("Принадлежность к соцсети / источнику", lead["source"])

        # и адрес
        if lead.get("address"):
            _set_cf("Общий адрес", lead["address"])


# singleton
clickup_client = ClickUpClient(space_id=SPACE_ID, team_id=TEAM_ID)
