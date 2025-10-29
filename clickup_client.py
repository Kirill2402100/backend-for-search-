import requests
from typing import Optional, Dict, Any, List
from config import settings

# Статусы по умолчанию (можно переопределить через переменные окружения)
READY_STATUS    = getattr(settings, "CLICKUP_STATUS_READY",    "взял в работу")   # «Готовые к отправке»
SENT_STATUS     = getattr(settings, "CLICKUP_STATUS_SENT",     "кп отправлено")
REPLIED_STATUS  = getattr(settings, "CLICKUP_STATUS_REPLIED",  "звонок назначен") # при получении ответа
INVALID_STATUS  = getattr(settings, "CLICKUP_STATUS_INVALID",  "невалидный")      # если такого статуса нет — поставим тег


class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self):
        self.headers = {
            "Authorization": settings.CLICKUP_API_TOKEN,
            "Content-Type": "application/json",
        }

    # ---------- Lists ----------
    def get_or_create_list_for_state(self, state: str) -> str:
        lists_url = f"{self.BASE_URL}/space/{settings.CLICKUP_SPACE_ID}/list"
        resp = requests.get(lists_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        target_name = state.strip()
        for lst in data.get("lists", []):
            if lst.get("name", "").strip().lower() == target_name.lower():
                return lst["id"]

        create_url = f"{self.BASE_URL}/space/{settings.CLICKUP_SPACE_ID}/list"
        payload = {"name": target_name, "content": f"Leads for {target_name}", "status": "новый"}
        create_resp = requests.post(create_url, json=payload, headers=self.headers, timeout=10)
        create_resp.raise_for_status()
        return create_resp.json()["id"]

    def get_space_lists(self) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/space/{settings.CLICKUP_SPACE_ID}/list"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json().get("lists", [])

    # ---------- Tasks ----------
    def _build_description(
        self, website: Optional[str], email: Optional[str], source: Optional[str], extra: Optional[Dict[str, Any]]
    ) -> str:
        lines = []
        if website: lines.append(f"Website: {website}")
        if email:   lines.append(f"Email: {email}")
        if source:  lines.append(f"Source: {source}")
        if extra:
            for k, v in extra.items():
                lines.append(f"{k}: {v}")
        return "\n".join(lines)

    def _list_tasks(self, list_id: str) -> List[Dict[str, Any]]:
        url = f"{self.BASE_URL}/list/{list_id}/task"
        resp = requests.get(url, headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json().get("tasks", [])

    def _find_task_by_name_in_list(self, list_id: str, clinic_name: str) -> Optional[Dict[str, Any]]:
        for task in self._list_tasks(list_id):
            if task.get("name", "").strip().lower() == clinic_name.strip().lower():
                return task
        return None

    def _create_lead_task(self, list_id: str, clinic_name: str, description: str) -> str:
        url = f"{self.BASE_URL}/list/{list_id}/task"
        payload = {"name": clinic_name, "description": description, "status": "новый"}
        resp = requests.post(url, json=payload, headers=self.headers, timeout=15)
        resp.raise_for_status()
        return resp.json()["id"]

    def _update_lead_task(self, task_id: str, description: str) -> str:
        url = f"{self.BASE_URL}/task/{task_id}"
        resp = requests.put(url, json={"description": description}, headers=self.headers, timeout=15)
        resp.raise_for_status()
        return task_id

    def create_or_update_lead(
        self, state: str, clinic_name: str, website: Optional[str], email: Optional[str],
        source: Optional[str], extra_fields: Optional[Dict[str, Any]]
    ) -> str:
        list_id = self.get_or_create_list_for_state(state)
        desc = self._build_description(website, email, source, extra_fields)
        existing = self._find_task_by_name_in_list(list_id, clinic_name)
        return self._update_lead_task(existing["id"], desc) if existing else self._create_lead_task(list_id, clinic_name, desc)

    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        leads = []
        for task in self._list_tasks(list_id):
            desc = (task.get("text_content") or task.get("description") or "")
            website_val, email_val = None, None
            for raw in desc.splitlines():
                line = raw.strip()
                if website_val is None:
                    if line.lower().startswith("website:"): website_val = line.split(":", 1)[1].strip()
                    elif ("http://" in line or "https://" in line) and " " not in line: website_val = line
                if email_val is None:
                    if line.lower().startswith("email:"):   email_val = line.split(":", 1)[1].strip()
                    elif "@" in line and "." in line:       email_val = line
            leads.append({
                "task_id": task["id"],
                "clinic_name": task.get("name", "").strip(),
                "website": website_val,
                "email": email_val,
                "status": (task.get("status") or {}).get("status"),
                "list_id": list_id,
            })
        return leads

    def move_lead_to_status(self, task_id: str, new_status: str) -> bool:
        url = f"{self.BASE_URL}/task/{task_id}"
        resp = requests.put(url, json={"status": new_status}, headers=self.headers, timeout=15)
        if resp.status_code >= 400:
            # если статус не существует — не падаем
            return False
        return True

    def add_tag(self, task_id: str, tag: str) -> None:
        url = f"{self.BASE_URL}/task/{task_id}/tag/{tag}"
        requests.post(url, headers=self.headers, timeout=10)

    # Поиск задачи по email по всем листам Space (на случай ответа на письмо)
    def find_task_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        email_low = email.strip().lower()
        for lst in self.get_space_lists():
            for t in self._list_tasks(lst["id"]):
                desc = (t.get("text_content") or t.get("description") or "").lower()
                if email_low in desc:
                    return {"task_id": t["id"], "clinic_name": t.get("name", ""), "list_id": lst["id"]}
        return None


clickup_client = ClickUpClient()
