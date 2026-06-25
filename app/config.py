from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/english_bot",
    )
    session_secret: str = os.getenv("SESSION_SECRET", "english-whatsapp-bot-dev-secret")


settings = Settings()
