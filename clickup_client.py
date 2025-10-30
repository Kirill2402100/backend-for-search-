# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"

# статусы, которые мы хотим видеть на каждом «штатном» листе
DEFAULT_STATUSES = [
    {"status": "NEW", "type": "open", "color": "#d3d3d3"},
    {"status": "READY", "type": "open", "color": "#6a6ef7"},
    {"status": "SENT", "type": "done", "color": "#3ac35f"},
    {"status": "INVALID", "type": "closed", "color": "#f95c5c"},
]

READY_STATUS = "READY"
SENT_STATUS = "SENT"
REPLIED_STATUS = "REPLIED"  # у тебя он есть в telegram_bot
INVALID_STATUS = "INVALID"


class ClickUpError(RuntimeError):
    pass


class ClickUpClient:
    def __init__(
        self,
        token: str,
        team_id: str,
        space_id: str,
        template_list_id: Optional[str] = None,
    ) -> None:
        self.token = token
        self.team_id = team_id
        self.space_id = space_id
        # это может быть ПУСТО — тогда создаём простой лист
        self.template_list_id = (template_list_id or "").strip() or None

    # ------------- внутреннее -------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
        }

    def _raise_for(self, resp: requests.Response, msg: str) -> None:
        if not resp.ok:
            raise ClickUpError(f"{msg}: {resp.status_code} {resp.text}")

    # ------------- создание листа под штат -------------
    def _create_list_plain(self, state: str) -> str:
        """Создаём обычный лист без шаблона."""
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        payload: Dict[str, Any] = {
            "name": f"LEADS-{state}",
            # сразу положим статусы
            "statuses": DEFAULT_STATUSES,
        }
        r = requests.post(url, json=payload, headers=self._headers(), timeout=20)
        self._raise_for(r, "ClickUp create list (plain)")
        data = r.json()
        list_id = str(data["id"])
        return list_id

    def _create_list_from_template(self, state: str) -> Optional[str]:
        """Пробуем создать лист на основе ТЕМПЛЕЙТА (а не живого листа)."""
        if not self.template_list_id:
            return None
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        payload: Dict[str, Any] = {
            "name": f"LEADS-{state}",
            "template_id": self.template_list_id,
        }
        r = requests.post(url, json=payload, headers=self._headers(), timeout=25)
        if r.status_code == 200:
            data = r.json()
            list_id = str(data["id"])
            # на всякий случай всё равно подмешаем наши статусы —
            # если в шаблоне были свои, они перезапишутся нашими
            self._ensure_statuses(list_id)
            return list_id
        else:
            # тут как раз твой случай: мы передали ID живого листа,
            # а ClickUp сказал 400 → просто логируем и вернём None
            log.warning(
                "ClickUp: can't create list from template_id=%s -> %s %s",
                self.template_list_id,
                r.status_code,
                r.text[:200],
            )
            return None

    def _ensure_statuses(self, list_id: str) -> None:
        """Обновляем лист, чтобы там были нужные нам 4 статуса."""
        url = f"{CLICKUP_API_BASE}/list/{list_id}"
        payload = {
            "statuses": DEFAULT_STATUSES,
        }
        r = requests.put(url, json=payload, headers=self._headers(), timeout=20)
        if not r.ok:
            log.warning("ClickUp: can't update statuses for list %s: %s %s", list_id, r.status_code, r.text[:200])

    # ------------- публичное -------------
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        1. ищем список по имени LEADS-<STATE>
        2. если нет — создаём
        """
        # 1) получить все списки в Space
        # (у тебя их немного, можно так)
        url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        r = requests.get(url, headers=self._headers(), timeout=20)
        self._raise_for(r, "ClickUp get lists for space")
        data = r.json()
        target_name = f"LEADS-{state}"
        for lst in data.get("lists", []):
            if lst.get("name") == target_name:
                list_id = str(lst["id"])
                # и тут тоже прогоним на всякий случай статусы
                self._ensure_statuses(list_id)
                return list_id

        # 2) не нашли → создаём
        # сначала — из шаблона, если дали нормальный template_id
        list_id = self._create_list_from_template(state)
        if list_id:
            return list_id

        # если не вышло — обычный
        return self._create_list_plain(state)

    # ------------- чтение -------------
    def _list_custom_fields_map(self, list_id: str) -> Dict[str, str]:
        """
        Вернёт словарь:
            { "Email": "xxxxx", "Phone": "yyyyy", ... }
        чтобы мы могли потом сопоставлять по имени.
        Если на листе вообще нет полей — вернём {}.
        """
        url = f"{CLICKUP_API_BASE}/list/{list_id}/field"
        r = requests.get(url, headers=self._headers(), timeout=20)
        if not r.ok:
            log.warning("ClickUp: can't fetch custom fields for list %s: %s %s", list_id, r.status_code, r.text[:200])
            return {}
        fields = r.json().get("fields", [])
        out: Dict[str, str] = {}
        for f in fields:
            # бывает, что API отдаёт просто строку — поэтому страховка
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id") or "")
            name = str(f.get("name") or "")
            if fid and name:
                out[name] = fid
        return out

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Забираем ВСЕ задачи из листа (страницы пролистываем).
        Вернём в удобном виде.
        """
        tasks: List[Dict[str, Any]] = []
        page = 0
        field_map = self._list_custom_fields_map(list_id)

        while True:
            url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
            r = requests.get(
                url,
                params={"page": page, "subtasks": "true"},
                headers=self._headers(),
                timeout=25,
            )
            self._raise_for(r, "ClickUp get tasks from list")
            data = r.json()
            raw_tasks = data.get("tasks", [])
            if not raw_tasks:
                break

            for t in raw_tasks:
                item: Dict[str, Any] = {
                    "task_id": t["id"],
                    "name": t.get("name"),
                    "status": (t.get("status") or {}).get("status"),
                    "email": None,
                    "phone": None,
                    "website": None,
                    # чтобы уметь искать по email
                }
                # вытащим из кастомных полей
                for cf in t.get("custom_fields", []):
                    cid = cf.get("id")
                    val = cf.get("value")
                    if not cid or val is None:
                        continue
                    # пробуем по имени
                    for field_name, field_id in field_map.items():
                        if cid == field_id:
                            if field_name.lower().startswith("email"):
                                item["email"] = val
                            elif field_name.lower().startswith("phone") or field_name.lower().startswith("тел"):
                                item["phone"] = val
                            elif field_name.lower().startswith("url"):
                                item["website"] = val
                tasks.append(item)

            page += 1

        return tasks

    # ------------- upsert таски -------------
    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> str:
        """
        Создаёт (или обновляет) задачу для одной клиники.
        Сейчас делаем «create always», т.к. в leads.py мы и так отсеиваем дубликаты.
        """
        field_map = self._list_custom_fields_map(list_id)

        custom_fields: List[Dict[str, Any]] = []

        # мы не знаем ТВОИ точные названия полей, поэтому просто
        # пытаемся сопоставить по самым распространённым.
        def _maybe_add(field_title: str, value: Any) -> None:
            if not value:
                return
            fid = field_map.get(field_title)
            if not fid:
                return
            custom_fields.append({"id": fid, "value": value})

        _maybe_add("Номер телефона", lead.get("phone"))
        _maybe_add("Общий адрес электронной почты", lead.get("email"))
        _maybe_add("URL веб-сайта", lead.get("website"))
        _maybe_add("Принадлежность к сети", lead.get("network"))
        _maybe_add("Выявленные возможности", lead.get("notes"))

        payload: Dict[str, Any] = {
            "name": lead["name"],
            # ВАЖНО: создаём ВСЕГДА в NEW, как ты попросил
            "status": "NEW",
        }
        if custom_fields:
            payload["custom_fields"] = custom_fields

        url = f"{CLICKUP_API_BASE}/list/{list_id}/task"
        r = requests.post(url, json=payload, headers=self._headers(), timeout=25)
        self._raise_for(r, "ClickUp create lead task")
        data = r.json()
        return str(data["id"])

    # ------------- поиск и изменение статуса -------------
    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Ищем по всем листам space'а — задачу, у которой есть кастомное поле с таким email.
        Это нужно для /replies.
        """
        # сначала пройдёмся по листам
        lists_url = f"{CLICKUP_API_BASE}/space/{self.space_id}/list"
        r = requests.get(lists_url, headers=self._headers(), timeout=20)
        if not r.ok:
            log.warning("ClickUp: can't list lists for find_task_by_email: %s %s", r.status_code, r.text[:200])
            return None
        for lst in r.json().get("lists", []):
            list_id = str(lst["id"])
            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                if t.get("email") and t["email"].lower() == email_addr.lower():
                    # вернём всё, что знаем
                    return {
                        "task_id": t["task_id"],
                        "clinic_name": t.get("name") or "",
                    }
        return None

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        url = f"{CLICKUP_API_BASE}/task/{task_id}"
        r = requests.put(url, json={"status": status}, headers=self._headers(), timeout=20)
        self._raise_for(r, f"ClickUp move task {task_id} to {status}")


# инициализация клиента, как раньше
clickup_client = ClickUpClient(
    token=os.environ.get("CLICKUP_API_TOKEN", ""),
    team_id=os.environ.get("CLICKUP_TEAM_ID", ""),
    space_id=os.environ.get("CLICKUP_SPACE_ID", ""),
    template_list_id=os.environ.get("CLICKUP_TEMPLATE_LIST_ID", ""),  # может быть пусто
)
