import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.docs import create_docs_token, decode_docs_token
from app.core.logging import JsonFormatter, configure_logging, redact
from app.main import app


def test_public_swagger_and_openapi_are_disabled():
    assert app.docs_url is None
    assert app.openapi_url is None
    assert app.redoc_url is None


def test_openapi_schema_includes_docs_session_endpoint():
    token, expires_at = create_docs_token(secret="secret", tenant_id=1, username="admin", ttl_seconds=60)
    assert datetime.fromisoformat(expires_at).tzinfo is not None
    claims = decode_docs_token(token, secret="secret")
    assert claims["scope"] == "api-docs"

    body = app.openapi()
    assert body["info"]["title"] == "English WhatsApp Poll Bot API"
    assert "/api/v1/docs/session" in body["paths"]


def test_docs_token_rejects_tampering_and_expiry():
    token, _ = create_docs_token(secret="secret", tenant_id=1, username="admin", ttl_seconds=60)
    with pytest.raises(HTTPException):
        decode_docs_token(f"{token}tampered", secret="secret")

    expired, _ = create_docs_token(secret="secret", tenant_id=1, username="admin", ttl_seconds=-1)
    with pytest.raises(HTTPException) as exc:
        decode_docs_token(expired, secret="secret")
    assert exc.value.status_code == 401


def test_json_logging_is_parseable_and_redacts_secrets(tmp_path):
    log_file = tmp_path / "app.jsonl"
    configure_logging(
        SimpleNamespace(
            log_level="INFO",
            log_format="json",
            log_file=str(log_file),
            log_human_file="",
        )
    )

    import logging

    logging.getLogger("english_bot.test").info(
        "secret.event",
        extra={"request_id": "rid-1", "greenapi_api_token_instance": "token-value", "nested": {"password": "pw"}},
    )
    line = log_file.read_text(encoding="utf-8").strip()
    payload = json.loads(line)

    assert payload["message"] == "secret.event"
    assert payload["request_id"] == "rid-1"
    assert payload["greenapi_api_token_instance"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    assert redact({"api_key": "abc", "safe": "value"}) == {"api_key": "[REDACTED]", "safe": "value"}


def test_configure_logging_keeps_stdout_when_file_logging_is_enabled(tmp_path, capsys):
    log_file = tmp_path / "app.jsonl"
    configure_logging(
        SimpleNamespace(
            log_level="INFO",
            log_format="json",
            log_file=str(log_file),
            log_human_file="",
        )
    )

    import logging

    logging.getLogger("english_bot.test").info(
        "stdout.secret",
        extra={"request_id": "rid-stdout", "greenapi_api_token_instance": "token-value"},
    )
    for handler in logging.getLogger("english_bot").handlers:
        handler.flush()

    stdout_line = capsys.readouterr().out.strip()
    payload = json.loads(stdout_line)

    assert payload["message"] == "stdout.secret"
    assert payload["request_id"] == "rid-stdout"
    assert payload["greenapi_api_token_instance"] == "[REDACTED]"
    assert log_file.read_text(encoding="utf-8").strip()


def test_json_formatter_emits_expected_shape():
    import logging

    record = logging.LogRecord("english_bot.unit", logging.INFO, __file__, 1, "hello", (), None)
    record.request_id = "rid-2"
    payload = json.loads(JsonFormatter().format(record))

    assert payload["logger"] == "english_bot.unit"
    assert payload["message"] == "hello"
    assert payload["request_id"] == "rid-2"
