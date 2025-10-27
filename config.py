import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    CLICKUP_API_TOKEN: str
    CLICKUP_SPACE_ID: str
    CLICKUP_TEAM_ID: str

    SMTP_FROM: str
    SMTP_HOST: str
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_PORT: int

    EMAIL_VALIDATION_PROVIDER: str
    EMAIL_VALIDATION_API_KEY: str

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_CHAT_ID: str

    class Config:
        case_sensitive = True

settings = Settings(
    CLICKUP_API_TOKEN=os.getenv("CLICKUP_API_TOKEN", ""),
    CLICKUP_SPACE_ID=os.getenv("CLICKUP_SPACE_ID", ""),
    CLICKUP_TEAM_ID=os.getenv("CLICKUP_TEAM_ID", ""),
    SMTP_FROM=os.getenv("SMTP_FROM", ""),
    SMTP_HOST=os.getenv("SMTP_HOST", ""),
    SMTP_USERNAME=os.getenv("SMTP_USERNAME", ""),
    SMTP_PASSWORD=os.getenv("SMTP_PASSWORD", ""),
    SMTP_PORT=int(os.getenv("SMTP_PORT", "465")),
    EMAIL_VALIDATION_PROVIDER=os.getenv("EMAIL_VALIDATION_PROVIDER", "verifalia"),
    EMAIL_VALIDATION_API_KEY=os.getenv("EMAIL_VALIDATION_API_KEY", ""),
    TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN", ""),
    TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID", ""),
)
