from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from clickup_client import clickup_client
from email_validator import validate_email_if_needed
from send import router as send_router
from telegram_bot import handle_update
from config import settings

app = FastAPI(title="TapGrow Backend")
app.include_router(send_router)

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
    is_valid = None
    if lead.email:
        is_valid = validate_email_if_needed(lead.email)

    task_id = clickup_client.create_or_update_lead(
        state=lead.state,
        clinic_name=lead.clinic_name,
        website=lead.website,
        email=lead.email,
        source=lead.source,
        extra_fields={"validated": is_valid},
    )
    return {"clickup_task_id": task_id, "email_valid": is_valid}

# --- Telegram webhook ---
@app.post("/tg/webhook")
async def tg_webhook(request: Request, secret: str):
    if secret != getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "dev"):
        raise HTTPException(status_code=403, detail="forbidden")
    update = await request.json()
    return handle_update(update)
