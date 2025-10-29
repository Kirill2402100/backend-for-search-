# main.py
from typing import Any, Dict, Optional
import threading

from fastapi import FastAPI, Request, HTTPException

from config import settings
from telegram_bot import handle_update
from telegram_poller import start_polling, register_commands


app = FastAPI(title="backend-for-search", version="1.0.0")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True}


@app.post("/tg/webhook")
async def tg_webhook(request: Request, secret: Optional[str] = None) -> Dict[str, Any]:
    """
    Опциональная конечная точка для режима Webhook.
    Работает только если query-параметр ?secret= совпадает с TELEGRAM_WEBHOOK_SECRET.
    Телеграм отправляет JSON 'update' — пробрасываем его в handle_update().
    """
    expected = getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None)
    if not expected:
        # вебхук не включён конфигом
        raise HTTPException(status_code=404, detail="Webhook disabled")

    if secret != expected:
        raise HTTPException(status_code=403, detail="Invalid secret")

    update: Dict[str, Any] = await request.json()
    try:
        handle_update(update)
    except Exception as e:
        # не ломаем ответ Телеграму
        print(f"[webhook] handle_update error: {e}")
    return {"ok": True}


@app.get("/")
def root() -> Dict[str, Any]:
    """
    Простой корневой эндпоинт, чтобы быстро понять, что сервис жив,
    и какой режим бота включён.
    """
    return {
        "service": "backend-for-search",
        "polling": str(getattr(settings, "TELEGRAM_POLLING", "0")),
        "webhook_enabled": bool(getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None)),
    }


@app.on_event("startup")
def on_startup() -> None:
    """
    1) Регистрируем команды бота (меню) в Telegram.
    2) Если TELEGRAM_POLLING=1 — запускаем long-polling в отдельном потоке.
    """
    try:
        register_commands(settings.TELEGRAM_BOT_TOKEN)
        print("[startup] Telegram commands registered")
    except Exception as e:
        print(f"[startup] register_commands error: {e}")

    if str(getattr(settings, "TELEGRAM_POLLING", "0")) == "1":
        try:
            t = threading.Thread(target=start_polling, daemon=True)
            t.start()
            print("[startup] Telegram polling started")
        except Exception as e:
            print(f"[startup] start_polling error: {e}")
    else:
        print("[startup] Polling disabled (set TELEGRAM_POLLING=1 to enable)")
