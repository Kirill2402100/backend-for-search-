# main.py
import logging
import threading
from typing import Any, Dict

import requests
from fastapi import FastAPI, Request

from config import settings
from telegram_bot import handle_update  # только обработчик
from telegram_poller import start_polling  # только запуск поллера

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

app = FastAPI(title="lead-generator-backend")

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


def _set_telegram_commands() -> None:
    """
    Регистрируем команды прямо отсюда, не трогая telegram_bot.py.
    Так мы не зависим от того, есть ли там функция register_commands().
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN is empty, skip setMyCommands")
        return

    payload = {
        "commands": [
            {"command": "menu", "description": "Открыть меню со штатами"},
            {"command": "help", "description": "Справка по командам"},
            {"command": "collect", "description": "Создать лист / собрать по штату"},
            {"command": "search", "description": "То же, что /collect"},
            {"command": "send", "description": "Отправить письма"},
            {"command": "stats", "description": "Статистика по штату"},
            {"command": "replies", "description": "Разобрать входящие ответы"},
            {"command": "id", "description": "Показать мой chat id"},
        ]
    }
    url = TELEGRAM_API_BASE.format(token=token) + "/setMyCommands"
    try:
        r = requests.post(url, json=payload, timeout=10)
        logger.info("[tg] setMyCommands: %s %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("[tg] setMyCommands error: %s", e)


@app.on_event("startup")
def on_startup() -> None:
    # 1. зарегали команды
    _set_telegram_commands()

    # 2. запустили long-polling всегда
    def _run_poller() -> None:
        try:
            start_polling()
        except Exception as e:
            logger.exception("poller crashed: %s", e)

    th = threading.Thread(target=_run_poller, name="tg-poller", daemon=True)
    th.start()
    logger.info("poller thread started")


@app.get("/")
def root() -> Dict[str, Any]:
    return {"ok": True, "service": "lead-generator"}


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/tg/webhook")
async def tg_webhook(req: Request) -> Dict[str, Any]:
    """
    Резервный эндпоинт — если когда-нибудь включишь вебхук у телеги.
    Сейчас мы работаем по getUpdates.
    """
    data: Dict[str, Any] = await req.json()
    try:
        return handle_update(data)
    except Exception as e:
        logger.exception("webhook handler error: %s", e)
        return {"ok": True}
