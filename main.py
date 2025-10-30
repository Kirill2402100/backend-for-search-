# main.py
import logging
import threading
from typing import Any, Dict

from fastapi import FastAPI, Request

from config import settings
from telegram_bot import handle_update, register_commands
from telegram_poller import start_polling

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

app = FastAPI(title="lead-generator-backend")


@app.get("/")
def root() -> Dict[str, Any]:
    return {"ok": True, "service": "lead-generator"}


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/tg/webhook")
async def tg_webhook(req: Request) -> Dict[str, Any]:
    """
    На будущее — если решишь включить у бота webhook.
    Сейчас мы работаем по long-polling.
    """
    data: Dict[str, Any] = await req.json()
    try:
        return handle_update(data)
    except Exception as e:
        logger.exception("webhook handler error: %s", e)
        return {"ok": True}


@app.on_event("startup")
def on_startup() -> None:
    # 1. регистрируем команды у Telegram (это твоя логика из telegram_bot)
    try:
        register_commands()
        logger.info("Telegram commands registered")
    except Exception as e:
        logger.exception("register_commands error: %s", e)

    # 2. запускаем polling ВСЕГДА, без проверки env
    def _run_poller() -> None:
        try:
            start_polling()
        except Exception as e:
            logger.exception("Polling thread failed: %s", e)

    th = threading.Thread(target=_run_poller, name="tg-poller", daemon=True)
    th.start()
    logger.info("Polling thread started")
