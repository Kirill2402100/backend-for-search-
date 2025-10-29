# main.py
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

# наше
from config import settings
from clickup_client import clickup_client
from email_validator import validate_email_if_needed
from send import router as send_router
from telegram_bot import handle_update

# polling (без вебхука), включаем по TELEGRAM_POLLING=1
import threading
try:
    from telegram_poller import start_polling
except Exception:
    start_polling = None  # если файла нет — просто игнорируем


app = FastAPI(title="TapGrow Backend")

# Роуты рассылки (POST /send-proposals)
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
    """
    Добавить/обновить лид в ClickUp из скрипта сбора (FB/Google/Yelp и т.д.)
    В описание кладём website/email/source и помечаем результат валидации email (если есть).
    """
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


# --- Telegram: Webhook обработчик (опционально, если используешь вебхук) ---
@app.post("/tg/webhook")
async def tg_webhook(request: Request, secret: str):
    """
    Endpoint для Telegram webhook: /tg/webhook?secret=<TELEGRAM_WEBHOOK_SECRET>
    Если секрет не совпадает — 403.
    """
    if secret != getattr(settings, "TELEGRAM_WEBHOOK_SECRET", "dev"):
        raise HTTPException(status_code=403, detail="forbidden")
    update = await request.json()
    return handle_update(update)


# --- Telegram: Polling запуск при старте приложения (если включён) ---
@app.on_event("startup")
def _start_polling_if_enabled():
    """
    Включает long-polling, если TELEGRAM_POLLING=1.
    Одновременно webhook и polling использовать не нужно:
    - если включён webhook, сначала выключи его:
      https://api.telegram.org/bot<token>/deleteWebhook?drop_pending_updates=true
    """
    if str(getattr(settings, "TELEGRAM_POLLING", "0")) == "1" and start_polling:
        t = threading.Thread(target=start_polling, daemon=True)
        t.start()


# Локальный запуск (удобно для отладки)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
