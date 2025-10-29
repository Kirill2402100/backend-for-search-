# telegram_notifier.py
import logging
import requests
from typing import Optional, Dict, Any
from config import settings

logger = logging.getLogger("app")
TELEGRAM_API_BASE = "https://api.telegram.org"

def send_message(
    chat_id: int,
    text: str,
    parse_mode: Optional[str] = "HTML",
    reply_markup: Optional[Dict[str, Any]] = None,
    disable_web_page_preview: bool = True,
) -> None:
    """
    Универсальная отправка сообщений в Telegram.
    Поддерживает parse_mode и reply_markup (клавиатуру).
    """
    token = settings.TELEGRAM_BOT_TOKEN
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    r = requests.post(url, json=payload, timeout=15)
    if r.status_code != 200:
        logger.warning("[tg] sendMessage failed: %s %s", r.status_code, r.text)
