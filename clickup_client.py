import requests
from typing import Optional, Dict, Any, List
from main.config import settings
from main.models import LeadStatus

class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self):
        self.headers = {
            "Authorization": settings.CLICKUP_API_TOKEN,
            "Content-Type": "application/json"
        }

    # ----------------------------
    # 1. Получить или создать List по штату
    # ----------------------------
    def get_or_create_list_for_state(self, state: str) -> str:
        """
        Возвращает list_id для штата.
        Если листа с таким именем (например 'NY') нет — создаёт.
        """

        # 1. Получаем все листы в Space
        lists_url = f"{self.BASE_URL}/space/{settings.CLICKUP_SPACE_ID}/list"
        resp = requests.get(lists_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # 2. Ищем лист с нужным именем
        for lst in data.get("lists", []):
            if lst.get("name", "").strip().upper() == state.strip().upper():
                return lst["id"]

        # 3. Если лист не найден — создаём
        create_url = f"{self.BASE_URL}/space/{settings.CLICKUP_SPACE_ID}/list"
        payload = {
            "name": state,
            "content": f"Лиды стоматологий штата {state}",
            # можно сразу задать дефолтный статус "новый"
        }
        create_resp = requests.post(create_url, headers=self.headers, json=payload, timeout=10)
        create_resp.raise_for_status()
        created = create_resp.json()
        return created["id"]

    # ----------------------------
    # 2. Нормализация домена (чтобы не плодить дубликатов)
    # ----------------------------
    @staticmethod
    def _normalize_website(website: Optional[str]) -> Optional[str]:
        if not website:
            return None
        w = website.strip().lower()
        w = w.replace("http://", "").replace("https://", "")
        if w.endswith("/"):
            w = w[:-1]
        return w

    # ----------------------------
    # 3. Проверка дублей по email / website
    # ----------------------------
    def find_existing_task(
        self,
        list_id: str,
        email: Optional[str],
        website: Optional[str]
    ) -> Optional[str]:
        """
        Пытаемся найти задачу в листе по email или домену сайта.
        ClickUp не даёт идеальный search по кастомным полям через публичный API,
        поэтому MVP-подход: просто читаем все задачи листа и ищем совпадение.
        Для небольших листов это ок.
        """

        tasks_url = f"{self.BASE_URL}/list/{list_id}/task"
        resp = requests.get(tasks_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        normalized_site = self._normalize_website(website)

        for task in data.get("tasks", []):
            task_name = task.get("name", "").strip().lower()

            # сравнение по названию клиники? потом можно
            # сейчас по email/сайту сначала:
            # кастомные поля в ClickUp хранятся в `custom_fields`
            for field in task.get("custom_fields", []):
                field_name = field.get("name", "").lower()
                field_value = str(field.get("value", "")).strip().lower()

                # сравним email
                if email and "email" in field_name and field_value == email.strip().lower():
                    return task["id"]

                # сравним домен сайта
                if normalized_site and ("site" in field_name or "website" in field_name):
                    if self._normalize_website(field_value) == normalized_site:
                        return task["id"]

        return None

    # ----------------------------
    # 4. Создать или обновить лид (задачу)
    # ----------------------------
    def create_or_update_lead(
        self,
        state: str,
        clinic_name: str,
        website: Optional[str],
        email: Optional[str],
        source: str,
        extra_fields: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        - находит/создаёт лист для штата
        - проверяет дубликат по email/сайту
        - если дубль найден -> возвращает его task_id
        - если нет -> создаёт новую задачу
        """

        list_id = self.get_or_create_list_for_state(state)

        # дубликат?
        existing = self.find_existing_task(list_id, email=email, website=website)
        if existing:
            return existing  # возвращаем id уже существующей задачи

        # формируем тело новой задачи
        payload = {
            "name": clinic_name,
            "status": "новый",  # это твой статус в Space "Sales"
            "custom_fields": []
        }

        # добавляем полезные данные в кастомные поля, НО:
        # важно: у кастомных полей в ClickUp есть IDшники.
        # Сейчас мы не знаем их ID через этот чат,
        # поэтому на первой итерации можно просто положить часть данных в `description`.
        desc_lines = []
        if website:
            desc_lines.append(f"Website: {website}")
        if email:
            desc_lines.append(f"Email: {email}")
        if extra_fields:
            for k, v in extra_fields.items():
                if v:
                    desc_lines.append(f"{k}: {v}")
        desc_lines.append(f"Source: {source}")
        desc_lines.append(f"State: {state}")

        payload["description"] = "\n".join(desc_lines)

        # создаём задачу
        create_task_url = f"{self.BASE_URL}/list/{list_id}/task"
        resp = requests.post(create_task_url, headers=self.headers, json=payload, timeout=10)
        resp.raise_for_status()
        task = resp.json()
        return task["id"]

    # ----------------------------
    # 5. Меняем статус лида (для рассылки/ответов)
    # ----------------------------
    def update_lead_status(self, task_id: str, status: str):
        """
        Для упрощения: мы просто меняем статус задачи.
        В твоём Sales Space есть статусы:
        - "новый"
        - "взял в работу"
        - "ожидаем ответа"
        - "звонок назначен"
        - "кп отправлено"
        - "отказ клиента"
        - "сделка закрыта"
        """
        url = f"{self.BASE_URL}/task/{task_id}"
        payload = {
            "status": self._map_internal_status_to_clickup(status)
        }
        resp = requests.put(url, headers=self.headers, json=payload, timeout=10)
        resp.raise_for_status()
        return True

    def _map_internal_status_to_clickup(self, internal_status: str) -> str:
        """
        Наши внутренние статусы (LeadStatus.EMAIL_VALID и т.п.)
        -> статус колонки в ClickUp board.
        Это маппинг, который мы контролируем сами.
        """
        if internal_status == LeadStatus.EMAIL_VALID:
            return "взял в работу"
        if internal_status == LeadStatus.PROPOSAL_SENT:
            return "кп отправлено"
        if internal_status == LeadStatus.REPLIED:
            return "звонок назначен"
        if internal_status == LeadStatus.INVALID_EMAIL:
            return "отказ клиента"  # или можешь сделать отдельную колонку потом
        # default
        return "новый"

    # ----------------------------
    # 6. Получить лидов для рассылки
    # ----------------------------
    def get_leads_ready_to_send(self, state: str, limit: int) -> List[Dict[str, Any]]:
        """
        MVP: берём просто все задачи из листа штата и считаем "готовыми к рассылке"
        тех, у кого статус = 'взял в работу' (то есть EMAIL_VALID).
        Потом можно усложнить.
        """

        list_id = self.get_or_create_list_for_state(state)

        tasks_url = f"{self.BASE_URL}/list/{list_id}/task"
        resp = requests.get(tasks_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        leads = []
        for t in data.get("tasks", []):
            if t.get("status", {}).get("status") == "взял в работу":
                # пробуем достать email и сайт из description
                desc = t.get("description", "") or ""
                email_val = extract_from_description(desc, prefix="Email:")
                site_val = extract_from_description(desc, prefix="Website:")

                leads.append({
                    "clickup_task_id": t["id"],
                    "clinic_name": t.get("name", ""),
                    "email": email_val,
                    "website": site_val
                })

        return leads[:limit]

    # ----------------------------
    # 7. Статистика по штату
    # ----------------------------
    def get_state_stats(self, state: str) -> Dict[str, int]:
        """
        Возвращает счетчики:
        total,
        ready_to_send (status == 'взял в работу'),
        sent (status == 'кп отправлено'),
        replied (status == 'звонок назначен')
        """

        list_id = self.get_or_create_list_for_state(state)

        tasks_url = f"{self.BASE_URL}/list/{list_id}/task"
        resp = requests.get(tasks_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        total = 0
        ready_to_send = 0
        sent = 0
        replied = 0

        for t in data.get("tasks", []):
            total += 1
            status_name = t.get("status", {}).get("status", "").strip().lower()

            if status_name == "взял в работу":
                ready_to_send += 1
            elif status_name == "кп отправлено":
                sent += 1
            elif status_name == "звонок назначен":
                replied += 1

        return {
            "total": total,
            "ready_to_send": ready_to_send,
            "sent": sent,
            "replied": replied
        }

# простая утилита: вытащить значение из description по префиксу
def extract_from_description(desc: str, prefix: str) -> Optional[str]:
    """
    Ищет строки формата:
    'Email: something@clinic.com'
    'Website: https://...'
    """
    for line in desc.splitlines():
        line = line.strip()
        if line.lower().startswith(prefix.lower()):
            return line[len(prefix):].strip()
    return None

clickup_client = ClickUpClient()
