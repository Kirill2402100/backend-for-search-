import requests
from typing import Optional, Dict, Any, List
from config import settings


class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self):
        self.headers = {
            "Authorization": settings.CLICKUP_API_TOKEN,
            "Content-Type": "application/json",
        }

    # -------------------------------------------------
    # 1. Получить или создать List под штат
    # -------------------------------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Возвращает list_id для штата.
        Если лист с таким именем (например "NY") нет – создаёт.
        """

        # 1) получаем все листы в Space
        lists_url = f"{self.BASE_URL}/space/{settings.CLICKUP_SPACE_ID}/list"
        resp = requests.get(lists_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # 2) ищем лист с именем штата
        target_name = state.strip()
        for lst in data.get("lists", []):
            if lst.get("name", "").strip().lower() == target_name.lower():
                return lst["id"]

        # 3) если такого нет — создаём
        create_url = f"{self.BASE_URL}/space/{settings.CLICKUP_SPACE_ID}/list"
        payload = {
            "name": target_name,
            "content": f"Leads for {target_name}",
            "due_date": None,
            "due_date_time": False,
            "priority": None,
            "assignee": None,
            "status": "новый",  # стартовый статус
        }
        create_resp = requests.post(create_url, json=payload, headers=self.headers, timeout=10)
        create_resp.raise_for_status()
        created = create_resp.json()

        return created["id"]

    # -------------------------------------------------
    # 2. Вспомогалка: собрать текст описания лида
    # -------------------------------------------------
    def _build_description(
        self,
        website: Optional[str],
        email: Optional[str],
        source: Optional[str],
        extra_fields: Optional[Dict[str, Any]],
    ) -> str:
        lines = []

        if website:
            lines.append(f"Website: {website}")
        if email:
            lines.append(f"Email: {email}")
        if source:
            lines.append(f"Source: {source}")

        if extra_fields:
            for k, v in extra_fields.items():
                lines.append(f"{k}: {v}")

        # Соединим в многострочный текст для ClickUp description
        return "\n".join(lines)

    # -------------------------------------------------
    # 3. Найти задачу в листе по названию клиники
    # -------------------------------------------------
    def _find_task_by_name_in_list(self, list_id: str, clinic_name: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает JSON задачи если нашли таск с таким именем в list_id.
        Иначе None.
        """
        url = f"{self.BASE_URL}/list/{list_id}/task"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        for task in data.get("tasks", []):
            if task.get("name", "").strip().lower() == clinic_name.strip().lower():
                return task

        return None

    # -------------------------------------------------
    # 4. Создать новую задачу-лид
    # -------------------------------------------------
    def _create_lead_task(
        self,
        list_id: str,
        clinic_name: str,
        description: str,
    ) -> str:
        """
        Создаёт задачу в ClickUp листе (лид) и возвращает её task_id.
        Ставит статус "новый".
        """
        url = f"{self.BASE_URL}/list/{list_id}/task"
        payload = {
            "name": clinic_name,
            "description": description,
            "status": "новый",
        }
        resp = requests.post(url, json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        task = resp.json()
        return task["id"]

    # -------------------------------------------------
    # 5. Обновить существующую задачу-лид (описание, статус не трогаем)
    # -------------------------------------------------
    def _update_lead_task(
        self,
        task_id: str,
        description: str,
    ) -> str:
        """
        Обновляет description у существующей задачи.
        Возвращает task_id обратно.
        """
        url = f"{self.BASE_URL}/task/{task_id}"
        payload = {
            "description": description,
        }
        resp = requests.put(url, json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return task_id

    # -------------------------------------------------
    # 6. Публичный метод: создать или обновить лида
    # -------------------------------------------------
    def create_or_update_lead(
        self,
        state: str,
        clinic_name: str,
        website: Optional[str],
        email: Optional[str],
        source: Optional[str],
        extra_fields: Optional[Dict[str, Any]],
    ) -> str:
        """
        1. Находим/создаём лист по штату
        2. Проверяем, есть ли уже таск с таким clinic_name
        3. Если да -> апдейтим описание (чтобы не было дубликатов)
        4. Если нет -> создаём таск со статусом "новый"
        """

        list_id = self.get_or_create_list_for_state(state)

        description = self._build_description(
            website=website,
            email=email,
            source=source,
            extra_fields=extra_fields,
        )

        existing_task = self._find_task_by_name_in_list(list_id, clinic_name)

        if existing_task:
            task_id = existing_task["id"]
            return self._update_lead_task(task_id, description)
        else:
            task_id = self._create_lead_task(list_id, clinic_name, description)
            return task_id

    # -------------------------------------------------
    # 7. Получить всех лидов (таски) из листа штата
    # -------------------------------------------------
    def get_leads_from_list(self, list_id: str) -> List[Dict[str, Any]]:
        """
        Возвращает массив лидов вида:
        [
            {
                "task_id": "...",
                "clinic_name": "...",
                "website": "...",
                "email": "..."
            },
            ...
        ]

        Парсит site/email из description.
        """

        url = f"{self.BASE_URL}/list/{list_id}/task"
        resp = requests.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        leads: List[Dict[str, Any]] = []

        for task in data.get("tasks", []):
            task_id = task["id"]
            clinic_name = task.get("name", "").strip()

            # ClickUp может хранить текст и в description, и в text_content (рендер html)
            description = (
                task.get("text_content")
                or task.get("description")
                or ""
            )

            website_val = None
            email_val = None

            # Грубый парсинг строк
            for raw_line in description.splitlines():
                line = raw_line.strip()

                # сайт
                if website_val is None:
                    if line.lower().startswith("website:"):
                        website_val = line.split(":", 1)[1].strip()
                    elif ("http://" in line or "https://" in line) and " " not in line:
                        # fallback
                        website_val = line

                # email
                if email_val is None:
                    if line.lower().startswith("email:"):
                        email_val = line.split(":", 1)[1].strip()
                    elif "@" in line and "." in line:
                        # fallback: возьмём первое что похоже на email
                        email_val = line

            leads.append(
                {
                    "task_id": task_id,
                    "clinic_name": clinic_name,
                    "website": website_val,
                    "email": email_val,
                }
            )

        return leads

    # -------------------------------------------------
    # 8. Переместить лида в другой статус (колонку)
    # -------------------------------------------------
    def move_lead_to_status(self, task_id: str, new_status: str) -> bool:
        """
        Обновляет статус задачи (например 'кп отправлено').
        """
        url = f"{self.BASE_URL}/task/{task_id}"
        payload = {
            "status": new_status
        }
        resp = requests.put(url, json=payload, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return True


# один глобальный клиент, который можно импортировать и переиспользовать
clickup_client = ClickUpClient()
