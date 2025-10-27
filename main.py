from fastapi import FastAPI, HTTPException
from main.clickup_client import clickup_client
from main.email_validator import validate_email_if_needed
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="TapGrow Backend")

class LeadIn(BaseModel):
    state: str
    clinic_name: str
    website: Optional[str] = None
    email: Optional[str] = None
    source: str = "facebook"

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/lead/from_fb")
def add_lead(lead: LeadIn):
    # 1. валидация email (если есть)
    is_valid = None
    if lead.email:
        is_valid = validate_email_if_needed(lead.email)

    # 2. создаём/обновляем лид в ClickUp
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

    return {
        "clickup_task_id": task_id,
        "email_valid": is_valid,
    }

@app.get("/state/stats/{state}")
def state_stats(state: str):
    stats = clickup_client.get_state_stats(state)
    if not stats:
        raise HTTPException(status_code=404, detail="No data")
    return stats
