from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(secret: str, data: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), data.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_docs_token(*, secret: str, tenant_id: int, username: str, ttl_seconds: int) -> tuple[str, str]:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64encode(
        json.dumps(
            {
                "sub": str(tenant_id),
                "username": username,
                "tenant_id": tenant_id,
                "scope": "api-docs",
                "exp": int(expires_at.timestamp()),
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_sign(secret, signing_input)}", expires_at.isoformat()


def decode_docs_token(token: str, *, secret: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid docs token") from exc
    signing_input = f"{header}.{payload}"
    if not hmac.compare_digest(_sign(secret, signing_input), signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid docs token")
    try:
        claims = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid docs token") from exc
    if claims.get("scope") != "api-docs":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid docs token")
    if int(claims.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Docs token expired")
    return claims
