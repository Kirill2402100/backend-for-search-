# telegram_poller.py
import time
from typing import Dict, Any
import requests

from config import settings
from telegram_bot import handle_update   # только обработчик

TELEGRAM_API_BASE = "https://api.telegram.org"  # локально, чтобы не было циклического импорта


def _delete_webhook(token: str) -> None:
    try:
        r = requests.get(f"{TELEGRAM_API_BASE}/bot{token}/deleteWebhook", timeout=10)
        print(f"[poller] deleteWebhook: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[poller] deleteWebhook error: {e}")


def start_polling() -> None:
    """
    Длинный long-polling в отдельном потоке/трейде.
    Работает, только если TELEGRAM_POLLING='1'.
    """
    if str(getattr(settings, "TELEGRAM_POLLING", "")).strip() != "1":
        print("Polling disabled (set TELEGRAM_POLLING=1 to enable)")
        return

    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("[poller] TELEGRAM_BOT_TOKEN is empty")
        return

    # если вдруг был выставлен вебхук — убираем
    _delete_webhook(token)

    offset = 0
    delay = int(getattr(settings, "TELEGRAM_POLLING_INTERVAL", 2))
    print("INFO:app:Polling started (TELEGRAM_POLLING='1')")

    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API_BASE}/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset + 1},
                timeout=35,
            )
            if resp.status_code != 200:
                time.sleep(delay)
                continue

            data: Dict[str, Any] = resp.json()
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0))
                try:
                    print(f"[poller] update {upd.get('update_id')} from chat "
                          f"{upd.get('message', {}).get('chat', {}).get('id')}")
                    handle_update(upd)
                except Exception as e:
                    print(f"[poller] handle_update error: {e}")

        except Exception as e:
            print(f"[poller] loop error: {e}")
            time.sleep(delay)
