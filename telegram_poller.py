# telegram_poller.py
import time
import requests
from typing import Dict, Any
from config import settings
from telegram_bot import handle_update
from telegram_notifier import TELEGRAM_API_BASE

def start_polling() -> None:
    """
    Простой лонг-поллинг в отдельном потоке.
    Если webhook включён — polling работать не будет, поэтому перед стартом
    сделай deleteWebhook (см. шаги ниже).
    """
    token = settings.TELEGRAM_BOT_TOKEN
    offset = 0
    poll_delay_sec = int(getattr(settings, "TELEGRAM_POLLING_INTERVAL", 2))

    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API_BASE}/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset + 1},
                timeout=35,
            )
            if resp.status_code != 200:
                time.sleep(poll_delay_sec)
                continue

            data: Dict[str, Any] = resp.json()
            for upd in data.get("result", []):
                offset = max(offset, upd.get("update_id", 0))
                # обрабатываем апдейт тем же кодом, что и webhook
                handle_update(upd)

        except Exception:
            # на любых сетевых/JSON ошибках — короткий бэк-офф и дальше
            time.sleep(5)
