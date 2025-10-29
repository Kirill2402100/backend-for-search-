import requests
from typing import Optional, Dict, Any
from config import settings

TELEGRAM_API_BASE = "https://api.telegram.org"


def _request(method: str, payload: Dict[str, Any]) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> bool:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _request("sendMessage", payload)


def send_telegram_message(text: str) -> bool:
    # отправка в фиксированный чат из настроек
    return send_message(int(settings.TELEGRAM_CHAT_ID), text)
