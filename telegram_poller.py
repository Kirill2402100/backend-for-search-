import time
import requests
from typing import Dict, Any

from config import settings
from telegram_bot import handle_update, TELEGRAM_API_BASE

def start_polling() -> None:
    """
    Простой long-polling без сторонних либ.
    Перед стартом снимаем вебхук, чтобы getUpdates работал.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("[poller] TELEGRAM_BOT_TOKEN is empty — polling exit")
        return

    # На всякий случай снимаем вебхук (если он был)
    try:
        r = requests.get(
            f"{TELEGRAM_API_BASE}/bot{token}/deleteWebhook",
            params={"drop_pending_updates": True},
            timeout=10,
        )
        print(f"[poller] deleteWebhook: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[poller] deleteWebhook error: {e}")

    offset = 0
    poll_delay_sec = 2

    print("[poller] started")
    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API_BASE}/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset + 1},
                timeout=35,
            )
            if resp.status_code != 200:
                print(f"[poller] getUpdates HTTP {resp.status_code}: {resp.text[:200]}")
                time.sleep(poll_delay_sec)
                continue

            data: Dict[str, Any] = resp.json()
            if not data.get("ok"):
                print(f"[poller] getUpdates fail: {data}")
                time.sleep(poll_delay_sec)
                continue

            results = data.get("result", [])
            for upd in results:
                offset = max(offset, int(upd.get("update_id", 0)))
                # Для наглядности логируем id апдейта и чат
                chat_id = (
                    upd.get("message", {}) or upd.get("edited_message", {}) or {}
                ).get("chat", {}).get("id")
                print(f"[poller] update {offset} from chat {chat_id}")
                try:
                    handle_update(upd)
                except Exception as e:
                    print(f"[poller] handle_update error: {e}")

        except Exception as e:
            print(f"[poller] loop error: {e}")
            time.sleep(poll_delay_sec)
