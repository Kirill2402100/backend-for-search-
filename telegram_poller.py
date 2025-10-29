# telegram_poller.py
import time
import requests
from typing import Dict, Any

from config import settings
from telegram_bot import handle_update
from telegram_notifier import TELEGRAM_API_BASE


def _delete_webhook(token: str) -> None:
    # на всякий случай снимем вебхук, чтобы polling точно работал
    try:
        requests.get(f"{TELEGRAM_API_BASE}/bot{token}/deleteWebhook",
                     params={"drop_pending_updates": True}, timeout=10)
    except Exception:
        pass


def register_commands(token: str) -> None:
    """
    Регистрируем команды, чтобы в Telegram появилось меню.
    Делается один раз при старте.
    """
    cmds = {
        "commands": [
            {"command": "menu",   "description": "Открыть меню"},
            {"command": "help",   "description": "Справка по командам"},
            {"command": "search", "description": "Сбор по штату: /search NY"},
            {"command": "send",   "description": "Отправить N писем: /send 50"},
            {"command": "status", "description": "Статистика по лидам"}
        ],
        "scope": {"type": "default"}
    }
    try:
        requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/setMyCommands",
            json=cmds,
            timeout=10
        )
    except Exception:
        pass


def start_polling() -> None:
    """
    Простой лонг-поллинг в отдельном потоке.
    Если вебхук был включён — polling не будет получать апдейты,
    поэтому снимаем вебхук перед стартом.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    poll_delay_sec = int(getattr(settings, "TELEGRAM_POLLING_INTERVAL", 2))

    _delete_webhook(token)       # на всякий случай
    register_commands(token)     # выставим меню

    offset = 0
    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API_BASE}/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset, "allowed_updates": ["message"]},
                timeout=35,
            )
            if resp.status_code != 200:
                time.sleep(poll_delay_sec)
                continue

            data: Dict[str, Any] = resp.json()
            for upd in data.get("result", []):
                # обрабатываем апдейт
                try:
                    handle_update(upd)
                except Exception:
                    pass
                # ВАЖНО: сдвигаем offset на последний update_id + 1
                offset = max(offset, int(upd.get("update_id", 0)) + 1)

        except Exception:
            time.sleep(poll_delay_sec)
            continue
