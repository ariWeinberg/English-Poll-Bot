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
    jwt_secret: str = os.getenv("JWT_SECRET", os.getenv("SESSION_SECRET", "english-whatsapp-bot-dev-secret"))
    jwt_ttl_minutes: int = int(os.getenv("JWT_TTL_MINUTES", "1440"))
    docs_token_ttl_seconds: int = int(os.getenv("DOCS_TOKEN_TTL_SECONDS", "300"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_format: str = os.getenv("LOG_FORMAT", "human")
    log_file: str = os.getenv("LOG_FILE", "logs/app.jsonl")
    log_human_file: str = os.getenv("LOG_HUMAN_FILE", "logs/app.log")
    log_request_body_enabled: bool = os.getenv("LOG_REQUEST_BODY_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


settings = Settings()
