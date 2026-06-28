from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import Request, Response
from fastapi.routing import APIRoute

SECRET_KEYS = {
    "authorization",
    "password",
    "token",
    "access_token",
    "api_token",
    "api_key",
    "greenapi_api_token_instance",
    "gemini_api_key",
    "jwt_secret",
    "session_secret",
}


def is_secret_key(key: str) -> bool:
    key_lower = key.lower()
    return key_lower in SECRET_KEYS or any(secret in key_lower for secret in ("token", "secret", "password"))


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if is_secret_key(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            }:
                continue
            payload[key] = "[REDACTED]" if is_secret_key(key) else redact(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(settings: Any) -> None:
    level = getattr(logging, str(settings.log_level).upper(), logging.INFO)
    logger = logging.getLogger("english_bot")
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    json_formatter = JsonFormatter()
    human_formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s request_id=%(request_id)s",
        defaults={"request_id": "-"},
    )

    if settings.log_file:
        Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
        json_handler = logging.FileHandler(settings.log_file)
        json_handler.setFormatter(json_formatter)
        logger.addHandler(json_handler)

    if settings.log_human_file:
        Path(settings.log_human_file).parent.mkdir(parents=True, exist_ok=True)
        human_handler = logging.FileHandler(settings.log_human_file)
        human_handler.setFormatter(human_formatter)
        logger.addHandler(human_handler)

    if not logger.handlers:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(json_formatter if settings.log_format == "json" else human_formatter)
        logger.addHandler(stream_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"english_bot.{name}")


class RequestLoggingRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Any]:
        original_route_handler = super().get_route_handler()
        route_logger = get_logger("request")

        async def route_handler(request: Request) -> Response:
            from app.config import settings

            request_id = request.headers.get("x-request-id") or uuid4().hex
            started = time.perf_counter()
            log_extra = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "client": request.client.host if request.client else None,
            }
            if settings.log_request_body_enabled and request.headers.get("content-type", "").startswith(
                "application/json"
            ):
                raw_body = await request.body()
                if raw_body:
                    try:
                        log_extra["request_body"] = redact(json.loads(raw_body))
                    except json.JSONDecodeError:
                        log_extra["request_body"] = "[unparseable-json]"
            route_logger.info("request.start", extra=log_extra)
            try:
                response = await original_route_handler(request)
            except Exception:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                route_logger.exception("request.exception", extra={**log_extra, "duration_ms": duration_ms})
                raise
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers["x-request-id"] = request_id
            route_logger.info(
                "request.finish",
                extra={**log_extra, "status_code": response.status_code, "duration_ms": duration_ms},
            )
            return response

        return route_handler
