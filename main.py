from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

from clickup_client import clickup_client
from email_validator import validate_email_if_needed
from send import router as send_router

app = FastAPI(title="TapGrow Backend")

# Подключаем маршруты для рассылки
app.include_router(send_router)


class LeadIn(BaseModel):
    state: str
    clinic_name: str
    website: Optional[str] = None
    email: Optional[str] = None
    source: str = "facebook"


@app.get("/health")
def health():
    """
    Проверка состояния сервера.
    """
    return {"ok": True}


@app.post("/lead/from_fb")
def add_lead(lead: LeadIn):
    """
    Эндпоинт для добавления лида из Facebook (или другого источника).
    Валидирует email, создаёт/обновляет лид в ClickUp.
    """

    is_valid = None
    if lead.email:
        try:
            is_valid = validate_email_if_needed(lead.email)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Email validation error: {e}")

    try:
        task_id = clickup_client.create_or_update_lead(
            state=lead.state,
            clinic_name=lead.clinic_name,
            website=lead.website,
            email=lead.email,
            source=lead.source,
            extra_fields={
                "validated": is_valid,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickUp error: {e}")

    return {
        "clickup_task_id": task_id,
        "email_valid": is_valid,
    }
