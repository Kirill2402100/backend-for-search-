import os
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    CLICKUP_API_TOKEN: str = Field(default="")
    CLICKUP_SPACE_ID: str = Field(default="")
    CLICKUP_TEAM_ID: str = Field(default="")

    SMTP_FROM: str = Field(default="")
    SMTP_HOST: str = Field(default="")
    SMTP_USERNAME: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_PORT: int = Field(default=465)

    EMAIL_VALIDATION_PROVIDER: str = Field(default="verifalia")
    EMAIL_VALIDATION_API_KEY: str = Field(default="")

    TELEGRAM_BOT_TOKEN: str = Field(default="")
    TELEGRAM_CHAT_ID: str = Field(default="")

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
