# telegram_poller.py
import time
import requests
from typing import Dict, Any
from config import settings
from telegram_bot import handle_update

TELEGRAM_API_BASE = "https://api.telegram.org/bot"

def _delete_webhook(token: str) -> None:
    try:
        r = requests.get(f"{TELEGRAM_API_BASE}{token}/deleteWebhook", timeout=10)
        print("[TG] deleteWebhook:", r.status_code, r.text)
    except Exception as e:
        print("[TG] deleteWebhook error:", e)

def start_polling() -> None:
    """
    Long-polling цикл. Перед стартом всегда выключаем webhook.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("[TG] No TELEGRAM_BOT_TOKEN provided.")
        return

    poll_delay = int(getattr(settings, "TELEGRAM_POLLING_INTERVAL", 2))

    # На всякий случай выключаем webhook
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
