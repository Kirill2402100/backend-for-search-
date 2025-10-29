from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import threading
import os
import logging

from config import settings
from telegram_bot import register_commands
from telegram_poller import start_polling

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

app = FastAPI(title="backend-for-search")

@app.get("/health")
def health():
    return {"ok": True}

# Webhook-эндпоинт остаётся (вдруг когда-то захочешь вернуться на вебхуки),
# но в текущей конфигурации мы работаем через polling.
@app.post("/tg/webhook")
async def tg_webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return JSONResponse({"ok": True})
    # намеренно ничего не делаем — сейчас используется polling
    return JSONResponse({"ok": True})

def _start_background_poller():
    try:
        start_polling()
    except Exception as e:
        logger.exception("Telegram polling crashed: %s", e)

@app.on_event("startup")
def on_startup():
    # 1) зарегистрировать команды бота в меню
    try:
        register_commands()
        logger.info("Telegram commands registered")
    except Exception as e:
        logger.warning("register_commands error: %s", e)

    # 2) при TELEGRAM_POLLING=1 — стартуем long-polling в отдельном потоке
    flag = str(getattr(settings, "TELEGRAM_POLLING", "0")).strip()
    enabled = flag in ("1", "true", "True", "yes", "on")
    if enabled:
        t = threading.Thread(target=_start_background_poller, daemon=True, name="tg-poller")
        t.start()
        logger.info("Telegram polling started in background thread")
    else:
        logger.info("Polling disabled (set TELEGRAM_POLLING=1 to enable)")
