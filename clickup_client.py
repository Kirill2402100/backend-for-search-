# clickup_client.py
import os
import logging
import requests
from typing import Any, Dict, List, Optional

log = logging.getLogger("clickup")

CLICKUP_API = "https://api.clickup.com/api/v2"

# наши целевые статусы
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"

# что хотим видеть в каждом листе
REQUIRED_STATUSES = [
    {"status": NEW_STATUS, "type": "open", "orderindex": 0, "color": "#5bc0de"},
    {"status": READY_STATUS, "type": "open", "orderindex": 1, "color": "#f0ad4e"},
    {"status": SENT_STATUS, "type": "done", "orderindex": 2, "color": "#5cb85c"},
    {"status": INVALID_STATUS, "type": "closed", "orderindex": 3, "color": "#d9534f"},
]

# кастомные поля, которые мы бы хотели (если тариф даст)
REQUIRED_FIELDS = {
    "Email": {"type": 4},       # 4 = text
    "Website": {"type": 4},
    "Facebook": {"type": 4},
    "Instagram": {"type": 4},
    "LinkedIn": {"type": 4},
}


class ClickUpError(Exception):
    pass


class ClickUpClient:
    def __init__(self) -> None:
        self.token = os.getenv("CLICKUP_API_TOKEN") or ""
        self.team_id = os.getenv("CLICKUP_TEAM_ID") or ""
        self.space_id = os.getenv("CLICKUP_SPACE_ID") or ""
        # не обязателен
        self.template_list_id = os.getenv("CLICKUP_TEMPLATE_LIST_ID") or ""
        # кэш: "NY" -> list_id
        self._state_lists: Dict[str, str] = {}

    # -------------------------------------------------
    # low-level http
    # -------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": self.token, "Content-Type": "application/json"}

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = requests.get(url, headers=self._headers(), params=params, timeout=20)
        if r.status_code >= 400:
            raise ClickUpError(f"GET {url} -> {r.status_code} {r.text}")
        return r.json()

    def _post(self, url: str, json: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(url, headers=self._headers(), json=json, timeout=20)
        if r.status_code >= 400:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")
        return r.json()

    def _put(self, url: str, json: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.put(url, headers=self._headers(), json=json, timeout=20)
        if r.status_code >= 400:
            raise ClickUpError(f"PUT {url} -> {r.status_code} {r.text}")
        return r.json()

    # -------------------------------------------------
    # helpers
    # -------------------------------------------------
    def _space_lists(self) -> List[Dict[str, Any]]:
        if not self.space_id:
            raise ClickUpError("CLICKUP_SPACE_ID is empty")
        url = f"{CLICKUP_API}/space/{self.space_id}/list"
        data = self._get(url)
        return data.get("lists", [])

    def _find_list_by_name(self, name: str) -> Optional[str]:
        for lst in self._space_lists():
            if lst.get("name") == name:
                return str(lst.get("id"))
        return None

    # -------------------------------------------------
    # statuses
    # -------------------------------------------------
    def _ensure_statuses_on_list(self, list_id: str) -> None:
        """
        Принудительно кладём в лист наши 4 статуса,
        даже если ClickUp создал его с русскими/дефолтными.
        """
        try:
            url = f"{CLICKUP_API}/list/{list_id}"
            payload = {
                "statuses": REQUIRED_STATUSES,
            }
            self._put(url, payload)
            log.info("clickup:normalized statuses on list %s", list_id)
        except Exception as e:
            # не хотим падать из-за этого
            log.warning("clickup:cannot normalize statuses on list %s: %s", list_id, e)

    # -------------------------------------------------
    # custom fields
    # -------------------------------------------------
    def _list_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_API}/list/{list_id}/field"
        data = self._get(url)
        return data.get("fields", [])

    def _create_field_on_list(self, list_id: str, name: str, field_type: int) -> Optional[str]:
        url = f"{CLICKUP_API}/list/{list_id}/field"
        payload = {"name": name, "type": field_type}
        r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
        # тут у тебя план часто возвращает 400 FIELD_033 -> просто варним и идём дальше
        if r.status_code >= 400:
            log.warning("clickup:cannot create field %s on list %s (no id in resp)", name, list_id)
            return None
        data = r.json()
        fid = data.get("id")
        if not fid:
            log.warning("clickup:cannot create field %s on list %s (no id in resp)", name, list_id)
            return None
        return str(fid)

    def _ensure_required_fields(self, list_id: str) -> Dict[str, str]:
        """
        Возвращаем карту: 'Email' -> field_id
        то что не удалось создать — просто не кладём в карту
        """
        existing = {f.get("name"): str(f.get("id")) for f in self._list_custom_fields(list_id) if f.get("id")}
        out: Dict[str, str] = {}
        for fname, cfg in REQUIRED_FIELDS.items():
            if fname in existing:
                out[fname] = existing[fname]
            else:
                fid = self._create_field_on_list(list_id, fname, cfg["type"])
                if fid:
                    out[fname] = fid
        return out

    # -------------------------------------------------
    # list management
    # -------------------------------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        if state in self._state_lists:
            return self._state_lists[state]

        list_name = f"LEADS-{state}"
        list_id = self._find_list_by_name(list_name)
        if not list_id:
            # создаём прямо в space
            if not self.space_id:
                raise ClickUpError("CLICKUP_SPACE_ID is empty")
            url = f"{CLICKUP_API}/space/{self.space_id}/list"
            payload = {"name": list_name}
            data = self._post(url, payload)
            list_id = str(data.get("id"))
            log.info("clickup:created list %s (%s)", list_id, list_name)

        # в любом случае ДОВОДИМ СТАТУСЫ ДО НУЖНЫХ
        self._ensure_statuses_on_list(list_id)
        # и пытаемся (по возможности) добавить поля
        self._ensure_required_fields(list_id)

        self._state_lists[state] = list_id
        return list_id

    # -------------------------------------------------
    # tasks
    # -------------------------------------------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Забираем ВСЕ задачи из списка постранично.
        ClickUp даёт по 100 штук.
        """
        all_tasks: List[Dict[str, Any]] = []
        page = 0
        while True:
            url = f"{CLICKUP_API}/list/{list_id}/task"
            params = {
                "page": page,
                "include_closed": True,
            }
            data = self._get(url, params=params)
            tasks = data.get("tasks", [])
            all_tasks.extend(tasks)
            if len(tasks) < 100:
                break
            page += 1
        return all_tasks

    def find_task_by_email(self, email_value: str) -> Optional[Dict[str, Any]]:
        # очень простой перебор по всем листам штатов из кэша
        for state, list_id in self._state_lists.items():
            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                if t.get("text_content") == email_value:
                    return {
                        "task_id": t.get("id"),
                        "clinic_name": t.get("name"),
                        "state": state,
                    }
        return None

    def create_task(
        self,
        list_id: str,
        name: str,
        status: str,
        custom_fields: Optional[Dict[str, str]] = None,
    ) -> str:
        url = f"{CLICKUP_API}/list/{list_id}/task"
        payload: Dict[str, Any] = {
            "name": name,
            "status": status,
        }
        if custom_fields:
            # custom_fields должен быть в формате:
            # [{"id": "...", "value": "..."}, ...]
            payload["custom_fields"] = [{"id": fid, "value": val} for fid, val in custom_fields.items() if val]

        r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
        if r.status_code == 400 and "Status not found" in r.text:
            # значит лист опять откатил нам статусы → ещё раз нормализуем и пробуем без статуса
            self._ensure_statuses_on_list(list_id)
            payload.pop("status", None)
            r = requests.post(url, headers=self._headers(), json=payload, timeout=20)

        if r.status_code >= 400:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")

        data = r.json()
        task_id = str(data.get("id"))
        log.info("clickup:created lead task %s on list %s (%s)", task_id, list_id, name)
        return task_id

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> bool:
        """
        Сейчас у нас простая логика: всегда создаём.
        lead = {
          "name": "...",
          "email": "...",
          "website": "...",
          "facebook": "...",
          ...
        }
        """
        # сопоставляем поля, которые реально есть
        field_map = self._ensure_required_fields(list_id)

        cf_values: Dict[str, str] = {}
        if "Email" in field_map and lead.get("email"):
            cf_values[field_map["Email"]] = lead["email"]
        if "Website" in field_map and lead.get("website"):
            cf_values[field_map["Website"]] = lead["website"]
        if "Facebook" in field_map and lead.get("facebook"):
            cf_values[field_map["Facebook"]] = lead["facebook"]
        if "Instagram" in field_map and lead.get("instagram"):
            cf_values[field_map["Instagram"]] = lead["instagram"]
        if "LinkedIn" in field_map and lead.get("linkedin"):
            cf_values[field_map["LinkedIn"]] = lead["linkedin"]

        # создаём задачу
        try:
            self.create_task(
                list_id=list_id,
                name=lead.get("name") or "Dental clinic",
                status=NEW_STATUS,
                custom_fields=cf_values,
            )
            return True
        except ClickUpError as e:
            # если тариф не даёт создавать поля — создаём вообще без них
            if "Custom field usages exceeded" in str(e):
                log.warning(
                    "clickup:ClickUp custom field limit reached on list %s -> creating task without custom fields",
                    list_id,
                )
                self.create_task(
                    list_id=list_id,
                    name=lead.get("name") or "Dental clinic",
                    status=NEW_STATUS,
                    custom_fields=None,
                )
                return True
            raise

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{CLICKUP_API}/task/{task_id}"
        self._put(url, {"status": status})


clickup_client = ClickUpClient()
