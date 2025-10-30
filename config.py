# config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- ClickUp ---
    CLICKUP_API_TOKEN: str = ""
    CLICKUP_TEAM_ID: str = ""
    CLICKUP_SPACE_ID: str = ""

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""          # можно пусто — тогда бот отвечает всем
    TELEGRAM_POLLING: str = "0"         # "1" => включить long polling
    TELEGRAM_POLLING_INTERVAL: int = 2  # сек между запросами, если вдруг ошибка

    # --- SMTP / почта ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # --- валидация email ---
    EMAIL_VALIDATION_PROVIDER: str = ""  # например, "abstractapi"
    EMAIL_VALIDATION_API_KEY: str = ""

    # --- Google / сбор клиник ---
    # ВАЖНО: это поле нужно, чтобы leads.py увидел ключ
    GOOGLE_PLACES_API_KEY: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
