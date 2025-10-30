# telegram_poller.py
import time
import logging
from typing import Dict, Any

import requests

from config import settings
from telegram_bot import handle_update, TELEGRAM_API_BASE  # возьмём базовый URL из бота

logger = logging.getLogger("app.poller")


def start_polling() -> None:
    """
    Простой long-polling.
    Запускается из main.py в отдельном потоке.
    Никаких проверок TELEGRAM_POLLING тут нет — всегда работаем.
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.warning("Polling not started: TELEGRAM_BOT_TOKEN is empty")
        return

    # на всякий случай — уберём webhook, чтобы getUpdates работал
    try:
        r = requests.get(f"{TELEGRAM_API_BASE}/bot{token}/deleteWebhook", timeout=10)
        logger.info("[poller] deleteWebhook: %s %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("[poller] deleteWebhook error: %s", e)

    offset = 0
    logger.info("Polling started (forced)")

    while True:
        try:
            resp = requests.get(
                f"{TELEGRAM_API_BASE}/bot{token}/getUpdates",
                params={
                    "timeout": 30,
                    "offset": offset + 1,
                    "allowed_updates": ["message", "edited_message"],
                },
                timeout=35,
            )
        except Exception as e:
            logger.warning("[poller] getUpdates error: %s", e)
            time.sleep(2)
            continue

        if resp.status_code != 200:
            logger.warning("[poller] bad status %s: %s", resp.status_code, resp.text[:200])
            time.sleep(2)
            continue

        data: Dict[str, Any] = resp.json()
        updates = data.get("result", [])

        if not updates:
            # нет апдейтов — ждём следующий
            continue

        for upd in updates:
            upd_id = upd.get("update_id", 0)
            offset = max(offset, upd_id)

            chat_id = (
                upd.get("message") or upd.get("edited_message") or {}
            ).get("chat", {}).get("id")
            logger.info("[poller] update %s from chat %s", upd_id, chat_id)

            try:
                handle_update(upd)
            except Exception as e:
                logger.exception("[poller] handle_update error: %s", e)

        # маленькая пауза, чтобы не долбить Telegram
        time.sleep(0.3)
