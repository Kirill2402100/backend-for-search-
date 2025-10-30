# clickup_client.py
import os
import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("clickup")
logging.basicConfig(level=logging.INFO)

# ===== ENV =====
CLICKUP_TOKEN = os.getenv("CLICKUP_API_TOKEN", "").strip()
SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "").strip()
TEAM_ID = os.getenv("CLICKUP_TEAM_ID", "").strip()  # сейчас почти не используем, но пусть будет
TEMPLATE_LIST_ID = os.getenv("CLICKUP_TEMPLATE_LIST_ID", "").strip()

BASE_URL = "https://api.clickup.com/api/v2"

# ===== OUR STATUSES (как в твоём NY-листе) =====
NEW_STATUS = "NEW"
READY_STATUS = "READY"
SENT_STATUS = "SENT"
INVALID_STATUS = "INVALID"
REPLIED_STATUS = "REPLIED"   # <- ЭТО ВАЖНО, чтобы telegram_bot не падал


def _headers() -> Dict[str, str]:
    return {
        "Authorization": CLICKUP_TOKEN,
        "Content-Type": "application/json",
    }


class ClickUpError(Exception):
    pass


class ClickUpClient:
    """
    Здесь:
    - создаём лист LEADS-<STATE> в указанном SPACE
    - если задан TEMPLATE_LIST_ID — копируем ИЗ НЕГО СТАТУСЫ
    - потом в любом случае создаём наши 5 полей EN: Email, Website, Facebook, Instagram, LinkedIn
    - создаём/читаем задачи
    """

    # -------------------------------------------------
    # INIT
    # -------------------------------------------------
    def __init__(self, space_id: str, team_id: str):
        if not CLICKUP_TOKEN:
            raise RuntimeError("CLICKUP_API_TOKEN is empty")
        if not space_id:
            raise RuntimeError("CLICKUP_SPACE_ID is empty")

        self.space_id = space_id
        self.team_id = team_id

    # -------------------------------------------------
    # LOW LEVEL
    # -------------------------------------------------
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

    # -------------------------------------------------
    # LISTS
    # -------------------------------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Ищем лист LEADS-<STATE> в текущем SPACE.
        Если нет — создаём.
        1) создаём пустой лист
        2) если есть TEMPLATE_LIST_ID -> копируем из него СТАТУСЫ
        3) создаём наши 5 полей (EN)
        """
        wanted_name = f"LEADS-{state}"

        # 1. поиск
        space_lists_url = f"{BASE_URL}/space/{self.space_id}/list"
        try:
            data = self._get(space_lists_url)
            for item in data.get("lists", []):
                if item.get("name") == wanted_name:
                    list_id = str(item["id"])
                    # на всякий случай убедимся, что нужные поля есть
                    self._ensure_standard_fields(list_id)
                    return list_id
        except Exception as e:
            log.warning("clickup: cannot list lists in space %s: %s", self.space_id, e)

        # 2. создание
        create_url = f"{BASE_URL}/space/{self.space_id}/list"
        payload = {"name": wanted_name}
        created = self._post(create_url, payload)
        list_id = str(created["id"])
        log.info("clickup: created list %s (%s)", wanted_name, list_id)

        # 3. если есть шаблон — копируем СТАТУСЫ только
        if TEMPLATE_LIST_ID:
            log.info(
                "clickup: will copy statuses & fields from template %s -> %s",
                TEMPLATE_LIST_ID,
                list_id,
            )
            self._copy_statuses_from_template(list_id, TEMPLATE_LIST_ID)
        else:
            log.warning("clickup: CLICKUP_TEMPLATE_LIST_ID is empty -> using default board statuses")

        # 4. наши 5 полей
        self._ensure_standard_fields(list_id)

        return list_id

    # -------------------------------------------------
    # TEMPLATE COPY (only statuses)
    # -------------------------------------------------
    def _copy_statuses_from_template(self, target_list_id: str, template_list_id: str) -> None:
        """
        Копируем ТОЛЬКО статусы с шаблона.
        Поля не копируем специально — у шаблона они русские.
        """
        try:
            t_info = self._get(f"{BASE_URL}/list/{template_list_id}")
            statuses = t_info.get("statuses") or []
            if not statuses:
                log.warning("clickup: template %s has no statuses", template_list_id)
                return

            # важно: тут мы реально заменяем статусы на листе
            self._put(
                f"{BASE_URL}/list/{target_list_id}",
                {"statuses": statuses},
            )
            log.info("clickup: statuses copied from %s to %s", template_list_id, target_list_id)
        except Exception as e:
            log.warning("clickup: copy statuses failed: %s", e)

    # -------------------------------------------------
    # CUSTOM FIELDS
    # -------------------------------------------------
    STANDARD_FIELDS = [
        ("Email", "text"),
        ("Website", "text"),
        ("Facebook", "text"),
        ("Instagram", "text"),
        ("LinkedIn", "text"),
    ]

    def _list_raw_custom_fields(self, list_id: str) -> List[Dict[str, Any]]:
        try:
            data = self._get(f"{BASE_URL}/list/{list_id}/field")
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning("clickup: cannot read fields from list %s: %s", list_id, e)
            return []

    def _create_custom_field(self, list_id: str, name: str, ftype: str = "text") -> Optional[str]:
        """
        Создаём одно поле. Если тариф не даёт — просто лог и None.
        """
        try:
            resp = requests.post(
                f"{BASE_URL}/list/{list_id}/field",
                headers=_headers(),
                json={"name": name, "type": ftype},
                timeout=15,
            )
            if resp.status_code >= 400:
                # тут как раз твоя ошибка: {"err":"Custom field usages exceeded for your plan","ECODE":"FIELD_033"}
                log.warning(
                    "clickup: cannot create field %s on list %s (%s): %s",
                    name,
                    list_id,
                    resp.status_code,
                    resp.text[:200],
                )
                return None
            j = resp.json()
            fid = str(j.get("id") or "")
            return fid or None
        except Exception as e:
            log.warning("clickup: exception when creating field %s on %s: %s", name, list_id, e)
            return None

    def _ensure_standard_fields(self, list_id: str) -> None:
        """
        Проверяем, что на листе есть наши 5 английских полей.
        Если чего-то нет — создаём.
        """
        existing = {f.get("name"): f.get("id") for f in self._list_raw_custom_fields(list_id)}
        for fname, ftype in self.STANDARD_FIELDS:
            if fname in existing:
                continue
            self._create_custom_field(list_id, fname, ftype)

    def _custom_fields_map(self, list_id: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for f in self._list_raw_custom_fields(list_id):
            name = f.get("name")
            fid = f.get("id")
            if name and fid:
                out[name] = str(fid)
        return out

    # -------------------------------------------------
    # TASKS
    # -------------------------------------------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Забираем все задачи из листа (с пагинацией).
        """
        url = f"{BASE_URL}/list/{list_id}/task"
        params = {"page": 0}
        out: List[Dict[str, Any]] = []

        while True:
            data = self._get(url, params=params)
            tasks = data.get("tasks") or []
            out.extend(tasks)
            if len(tasks) < 100:
                break
            params["page"] += 1

        return out

    def find_task_by_email(self, email_addr: str) -> Optional[Dict[str, Any]]:
        """
        Для обработки /replies — ищем задачу по Email.
        Ищем по ВСЕМ нашим LEADS-* листам в текущем SPACE.
        """
        space_lists_url = f"{BASE_URL}/space/{self.space_id}/list"
        data = self._get(space_lists_url)

        for item in data.get("lists", []):
            list_id = str(item["id"])
            tasks = self.get_leads_from_list(list_id)
            for t in tasks:
                for cf in (t.get("custom_fields") or []):
                    if cf.get("name") == "Email":
                        val = cf.get("value") or ""
                        if val and val.lower() == email_addr.lower():
                            return {
                                "task_id": t["id"],
                                "clinic_name": t.get("name") or "",
                            }
        return None

    def move_lead_to_status(self, task_id: str, status: str) -> None:
        self._put(f"{BASE_URL}/task/{task_id}", {"status": status})

    def upsert_lead(self, list_id: str, lead: Dict[str, Any]) -> None:
        """
        Сейчас делаем просто: всегда создаём новую задачу.
        """
        # нормальное имя
        name = (
            lead.get("name")
            or lead.get("title")
            or lead.get("business_name")
            or "Clinic"
        )

        # по умолчанию в NEW
        status = lead.get("status") or NEW_STATUS

        # создаём таску
        created = self._post(
            f"{BASE_URL}/list/{list_id}/task",
            {
                "name": name,
                "status": status,
            },
        )
        task_id = created["id"]

        # ставим кастомки
        cf_map = self._custom_fields_map(list_id)

        def _set_cf(field_name: str, value: Any) -> None:
            fid = cf_map.get(field_name)
            if not fid:
                return
            self._put(
                f"{BASE_URL}/task/{task_id}/field/{fid}",
                {"value": value},
            )

        if lead.get("email"):
            _set_cf("Email", lead["email"])
        if lead.get("website"):
            _set_cf("Website", lead["website"])
        if lead.get("facebook"):
            _set_cf("Facebook", lead["facebook"])
        if lead.get("instagram"):
            _set_cf("Instagram", lead["instagram"])
        if lead.get("linkedin"):
            _set_cf("LinkedIn", lead["linkedin"])

        # если вдруг ты захочешь класть address/source – можно добавить сюда же
        # но сейчас ты просил только эти 5
        log.info("clickup: created lead task %s on list %s (%s)", task_id, list_id, name)


# singleton
clickup_client = ClickUpClient(space_id=SPACE_ID, team_id=TEAM_ID)
