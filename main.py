# main.py
import os
import threading
import logging
from typing import Any, Dict

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings
from telegram_bot import handle_update
from telegram_poller import start_polling  # <-- только start_polling, без register_commands

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

app = FastAPI(title="lead-generator")

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN


def _truthy(val: Any) -> bool:
    """Надёжно приводим значение из ENV к bool."""
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "on")


def _delete_webhook() -> None:
    try:
        url = (TELEGRAM_API_BASE + "/deleteWebhook").format(token=BOT_TOKEN)
        r = requests.get(url, timeout=10)
        log.info("[tg] deleteWebhook: %s %s", r.status_code, r.text)
    except Exception as e:
        log.warning("[tg] deleteWebhook error: %s", e)


def _set_commands() -> None:
    """Регистрируем команды в меню Telegram (без зависимостей от telegram_poller)."""
    try:
        payload = {
            "commands": [
                {"command": "menu", "description": "Открыть меню со штатами"},
                {"command": "help", "description": "Справка по командам"},
                {"command": "search", "description": "Сбор/лист для штата: /search NY"},
                {"command": "send", "description": "Отправить N писем: /send 50 (или /send NY 50)"},
                {"command": "stats", "description": "Статистика по штату: /stats NY"},
                {"command": "replies", "description": "Разобрать входящие ответы"},
            ]
        }
        url = (TELEGRAM_API_BASE + "/setMyCommands").format(token=BOT_TOKEN)
        r = requests.post(url, json=payload, timeout=10)
        log.info("[tg] setMyCommands: %s %s", r.status_code, r.text)
    except Exception as e:
        log.warning("[tg] setMyCommands error: %s", e)


@app.on_event("startup")
def on_startup() -> None:
    # 1) Регистрируем команды
    _set_commands()

    # 2) На всякий случай выключаем webhook (иначе getUpdates не работает)
    _delete_webhook()

    # 3) Стартуем polling, если включён флагом
    enabled_env = os.getenv("TELEGRAM_POLLING", getattr(settings, "TELEGRAM_POLLING", "0"))
    polling_enabled = _truthy(enabled_env)
    if polling_enabled:
        th = threading.Thread(target=start_polling, name="tg-poller", daemon=True)
        th.start()
        log.info("Polling started (TELEGRAM_POLLING=%r)", enabled_env)
    else:
        log.info("Polling disabled (set TELEGRAM_POLLING=1 to enable)")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/")
def root():
    return {"ok": True, "service": "lead-generator"}


@app.post("/tg/webhook")
async def tg_webhook(req: Request):
    """Оставлен на будущее: если решите вернуться к webhook-режиму."""
    try:
        upd: Dict[str, Any] = await req.json()
    except Exception:
        return JSONResponse({"ok": True})

    try:
        return JSONResponse(handle_update(upd))
    except Exception as e:
        log.exception("webhook handler error: %s", e)
        return JSONResponse({"ok": True})
