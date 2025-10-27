import requests
from main.config import settings

class ClickUpClient:
    BASE_URL = "https://api.clickup.com/api/v2"

    def __init__(self):
        self.headers = {
            "Authorization": settings.CLICKUP_API_TOKEN,
            "Content-Type": "application/json"
        }

    def ensure_list_for_state(self, state: str) -> str:
        raise NotImplementedError

    def create_or_update_lead(self, state: str, clinic_name: str, website: str | None,
                              email: str | None, source: str, extra_fields: dict | None = None) -> str:
        raise NotImplementedError

    def update_lead_status(self, task_id: str, status: str):
        raise NotImplementedError

    def get_leads_ready_to_send(self, state: str, limit: int):
        raise NotImplementedError

    def get_state_stats(self, state: str):
        raise NotImplementedError

clickup_client = ClickUpClient()
