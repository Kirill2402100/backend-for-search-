# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests

log = logging.getLogger("clickup")

CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "")
CLICKUP_TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "")
CLICKUP_SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "")
# этот айди у тебя уже есть в Railway
CLICKUP_TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "")

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"


# наши статусы, которые мы хотим иметь в КАЖДОМ листе
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"

REQUIRED_CUSTOM_FIELDS = [
    ("Email", "text"),
    ("Website", "url"),
    ("Facebook", "url"),
    ("Instagram", "url"),
    ("LinkedIn", "url"),
]


class ClickUpError(Exception):
    pass


class ClickUpClient:
    def __init__(self) -> None:
        if not CLICKUP_API_TOKEN:
            raise RuntimeError("CLICKUP_API_TOKEN is not set")
        if not CLICKUP_SPACE_ID:
            raise RuntimeError("CLICKUP_SPACE_ID is not set")
        self.token = CLICKUP_API_TOKEN
        self.space_id = CLICKUP_SPACE_ID
        self.team_id = CLICKUP_TEAM_ID
        self.template_list_id = CLICKUP_TEMPLATE_LIST_ID
        # кэш статусов по листу
        self._list_statuses: Dict[str, List[Dict[str, Any]]] = {}
        # кэш кастомных полей по листу
        self._list_fields: Dict[str, Dict[str, str]] = {}

    # ------------- базовые HTTP -------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    def _get(self, url: str, **kwargs) -> Dict[str, Any]:
        r = requests.get(url, headers=self._headers(), timeout=15, **kwargs)
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

    # ------------- статусы -------------
    def _default_statuses_payload(self) -> List[Dict[str, Any]]:
        # эти названия должны совпадать с тем, что мы используем в коде
        return [
            {"status": NEW_STATUS, "color": "#cccccc", "type": "custom"},
            {"status": READY_STATUS, "color": "#8C67FF", "type": "custom"},
            {"status": SENT_STATUS, "color": "#0066ff", "type": "custom"},
            {"status": INVALID_STATUS, "color": "#ff0000", "type": "custom"},
            {"status": REPLIED_STATUS, "color": "#14a44d", "type": "custom"},
        ]

    def _fetch_list_statuses(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_API_BASE}/list/{list_id}"
        data = self._get(url)
        sts = data.get("statuses") or []
        self._list_statuses[list_id] = sts
        return sts

    def get_list_statuses(self, list_id: str) -> List[Dict[str, Any]]:
        if list_id in self._list_statuses:
            return self._list_statuses[list_id]
        return self._fetch_list_statuses(list_id)

    def _list_has_status(self, list_id: str, status: str) -> bool:
        sts = self.get_list_statuses(list_id)
        for s in sts:
            if (s.get("status") or "").upper() == status.upper():
                return True
        return False

    # ------------- кастомные поля -------------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        # кэш
        if list_id in self._list_fields:
            return self._list_fields[list_id]

        url = f"{CLICKUP_API_BASE}/list/{list_id}/field"
        r = requests.get(url, headers=self._headers(), timeout=15)
        if r.status_code >= 400:
            # бывает 404 у списков без полей
            log.warning("cannot fetch fields for list %s: %s %s", list_id, r.status_code, r.text[:200])
            self._list_fields[list_id] = {}
            return {}

        data = r.json()
        fields = {}
        for f in data.get("fields", []):
            fid = str(f.get("id") or "")
            name = (f.get("name") or "").strip()
            if fid and name:
                fields[name] = fid
        self._list_fields[list_id] = fields
        return fields

    def _create_field_on_list(self, list_id: str, name: str, ftype: str) -> Optional[str]:
        # WARNING: у тебя платный/ограниченный план и он иногда отвечает
        # {"err":"Custom field usages exceeded for your plan","ECODE":"FIELD_033"}
        url = f"{CLICKUP_API_BASE}/list/{list_id}/field"
        payload = {"name": name, "type": ftype}
        r = requests.post(url, headers=self._headers(), json=payload, timeout=20)
        if r.status_code >= 400:
            log.warning("cannot create field %s on list %s (no id in resp)", name, list_id)
            return None
        data = r.json()
        fid = str(data.get("id") or "")
        if not fid:
            log.warning("cannot create field %s on list %s (no id in resp)", name, list_id)
            return None
        # дописываем в кэш
        cur = self._list_fields.get(list_id, {})
        cur[name] = fid
        self._list_fields[list_id] = cur
        return fid

    def _ensure_required_fields(self, list_id: str) -> Dict[str, str]:
        field_map = self._list_custom_fields_map(list_id)
        for field_name, ftype in REQUIRED_CUSTOM_FIELDS:
            if field_name not in field_map:
                fid = self._create_field_on_list(list_id, field_name, ftype)
                if fid:
                    field_map[field_name] = fid
        return field_map

    # ------------- создание / поиск листа -------------
    def _find_list_by_name(self, name: str) -> Optional[str]:
        # получаем все списки из пространства и ищем по имени
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list?archived=false"
        data = self._get(url)
        for item in data.get("lists", []):
            if (item.get("name") or "").strip().upper() == name.upper():
                return str(item.get("id"))
        return None

    def _create_list(self, name: str) -> str:
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        payload: Dict[str, Any] = {
            "name": name,
            "content": f"Leads for {name}",
            # вот тут самое главное — сразу кладём наши статусы
            "statuses": self._default_statuses_payload(),
            "assignee": None,
        }
        data = self._post(url, json=payload)
        list_id = str(data["id"])
        # обновим кэш статусов
        self._list_statuses[list_id] = data.get("statuses") or []
        log.info("clickup:created list %s (%s)", list_id, name)
        return list_id

    def get_or_create_list_for_state(self, state: str) -> str:
        name = f"LEADS-{state}"
        list_id = self._find_list_by_name(name)
        if list_id:
            return list_id
        # не нашли — создаём
        list_id = self._create_list(name)
        # и сразу пробуем создать обязательные поля (если тариф даст)
        self._ensure_required_fields(list_id)
        return list_id

    # ------------- задачи -------------
    def create_task(
        self,
        list_id: str,
        name: str,
        status: str,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> str:
        # проверим, что статус реально есть в этом листе
        if not self._list_has_status(list_id, status):
            # если нет — просто возьмём ПЕРВЫЙ статус этого листа
            sts = self.get_list_statuses(list_id)
            if sts:
                status = sts[0].get("status") or status
            else:
                # вообще пусто — пусть будет то, что просили
                pass

        url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
        payload: Dict[str, Any] = {
            "name": name,
            "status": status,
        }

        # пытаемся добавить кастомные поля, но если их слишком много — не падаем
        custom_values: List[Dict[str, Any]] = []
        if custom_fields:
            for fid, val in custom_fields.items():
                custom_values.append({"id": fid, "value": val})

        if custom_values:
            payload["custom_fields"] = custom_values

        r = requests.post(url, headers=self._headers(), json=payload, timeout=25)
        if r.status_code == 400 and "Custom field usages exceeded" in r.text:
            # создадим задачу без полей
            log.warning(
                "ClickUp custom field limit reached on list %s -> creating task without custom fields",
                list_id,
            )
            payload.pop("custom_fields", None)
            r = requests.post(url, headers=self._headers(), json=payload, timeout=25)

        if r.status_code >= 400:
            raise ClickUpError(f"POST {url} -> {r.status_code} {r.text}")

        data = r.json()
        task_id = str(data["id"])
        log.info("clickup:created lead task %s on list %s (%s)", task_id, list_id, name)
        return task_id

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{CLICKUP_API_BASE}/list/{list_id}/task?subtasks=true"
        data = self._get(url)
        return data.get("tasks", [])

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{CLICKUP_API_BASE}/task/{task_id}"
        payload = {"status": status}
        self._put(url, json=payload)

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Простейший поиск по всем спискам Sales — для твоего кейса ок.
        Можно потом сузить.
        """
        if not self.space_id:
            return None
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list?archived=false"
        data = self._get(url)
        for l in data.get("lists", []):
            lid = str(l.get("id"))
            tasks = self.get_leads_from_list(lid)
            for t in tasks:
                cfields = t.get("custom_fields") or []
                for cf in cfields:
                    name = (cf.get("name") or "").lower()
                    val = (cf.get("value") or "").lower()
                    if name == "email" and val == email_addr.lower():
                        return {
                            "task_id": t["id"],
                            "clinic_name": t.get("name") or "",
                        }
        return None

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> bool:
        """
        Пока что всегда создаём новый — ты пока не просил искать дубли по имени.
        Возвращаем True/False — создали ли.
        """
        name = lead["name"]
        # сначала гарантируем поля (если тариф позволит)
        field_map = self._ensure_required_fields(list_id)

        custom: Dict[str, Any] = {}
        if field_map:
            if lead.get("email"):
                fid = field_map.get("Email")
                if fid:
                    custom[fid] = lead["email"]
            if lead.get("website"):
                fid = field_map.get("Website")
                if fid:
                    custom[fid] = lead["website"]
            if lead.get("facebook"):
                fid = field_map.get("Facebook")
                if fid:
                    custom[fid] = lead["facebook"]
            if lead.get("instagram"):
                fid = field_map.get("Instagram")
                if fid:
                    custom[fid] = lead["instagram"]
            if lead.get("linkedin"):
                fid = field_map.get("LinkedIn")
                if fid:
                    custom[fid] = lead["linkedin"]

        self.create_task(
            list_id=list_id,
            name=name,
            status=NEW_STATUS,
            custom_fields=custom if custom else None,
        )
        return True


clickup_client = ClickUpClient()
