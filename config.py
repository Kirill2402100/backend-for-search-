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
    SMTP_PORT: int = 587                # 465 = SSL, 587 = STARTTLS
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # --- IMAP / «Отправленные» ---
    IMAP_HOST: str = ""                 # напр. imap.tapgrow.studio
    IMAP_PORT: int = 993                # обычно 993 (SSL)
    IMAP_USERNAME: str = ""
    IMAP_PASSWORD: str = ""
    IMAP_SENT_FOLDER: str = ""          # напр. "Sent" | "Sent Items" | "Отправленные"; если пусто — определяется автоматически
    BCC_SELF: int = 0                   # 1 = добавлять BCC на свой адрес, 0 = выключено

    # --- валидация email ---
    EMAIL_VALIDATION_PROVIDER: str = ""  # например, "abstractapi"
    EMAIL_VALIDATION_API_KEY: str = ""

    # --- Google / сбор клиник ---
    GOOGLE_PLACES_API_KEY: str = ""      # нужно, чтобы leads.py увидел ключ

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
