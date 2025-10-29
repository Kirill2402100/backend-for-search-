# telegram_poller.py
import time
import requests
from typing import Dict, Any, List
from config import settings
from telegram_bot import handle_update  # твой обработчик апдейтов

TELEGRAM_API_BASE = "https://api.telegram.org/bot"

def register_commands() -> None:
    """
    Регистрирует команды бота (меню в клиенте Telegram).
    Вызывается из main.py при старте.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("[TG] register_commands: no TELEGRAM_BOT_TOKEN")
        return

    commands: List[Dict[str, str]] = [
        {"command": "menu",   "description": "Открыть меню"},
        {"command": "help",   "description": "Справка по командам"},
        {"command": "search", "description": "Сбор по штату: /search NY"},
        {"command": "send",   "description": "Отправить N писем: /send 50"},
        {"command": "status", "description": "Статистика по лидам"},
    ]

    try:
        r = requests.post(
            f"{TELEGRAM_API_BASE}{token}/setMyCommands",
            json={"commands": commands},
            timeout=10,
        )
        print("[TG] setMyCommands:", r.status_code, r.text)
    except Exception as e:
        print("[TG] setMyCommands error:", e)


def _delete_webhook(token: str) -> None:
    """
    На всякий случай выключаем webhook перед стартом polling.
    Если webhook не стоял — вернётся ok=true, это нормально.
    """
    try:
        r = requests.get(f"{TELEGRAM_API_BASE}{token}/deleteWebhook", timeout=10)
        print("[TG] deleteWebhook:", r.status_code, r.text)
    except Exception as e:
        print("[TG] deleteWebhook error:", e)


def start_polling() -> None:
    """
    Long-polling цикл. Работает, только если TELEGRAM_POLLING=1.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("[TG] start_polling: no TELEGRAM_BOT_TOKEN")
        return

    poll_delay = int(getattr(settings, "TELEGRAM_POLLING_INTERVAL", 2))

    # гарантированно отключим webhook
    _delete_webhook(token)

    offset = 0
    print("[TG] Long-polling started")

    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API_BASE}{token}/getUpdates",
                params={"timeout": 30, "offset": offset + 1},
                timeout=35,
            )
            if resp.status_code != 200:
                print("[TG] getUpdates:", resp.status_code, resp.text)
                time.sleep(poll_delay)
                continue

            data: Dict[str, Any] = resp.json()
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0))
                try:
                    print("[TG] update:", upd.get("update_id"))
                    handle_update(upd)
                except Exception as e:
                    print("[TG] handle_update error:", e, "upd:", upd)

            time.sleep(poll_delay)

        except Exception as e:
            print("[TG] poll loop error:", e)
            time.sleep(poll_delay)
