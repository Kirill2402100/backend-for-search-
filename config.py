import os
from dotenv import load_dotenv

load_dotenv()  # загружает переменные из .env (на Railway будет браться из Environment Variables)

class Settings:
    CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "")
    CLICKUP_SPACE_ID = os.getenv("CLICKUP_SPACE_ID", "")
    CLICKUP_FOLDER_ID = os.getenv("CLICKUP_FOLDER_ID", "")

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")

    EMAIL_VALIDATION_API_KEY = os.getenv("EMAIL_VALIDATION_API_KEY", "")

settings = Settings()
