from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.database import db_session, get_tenant


security = HTTPBearer()


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(secret: str, data: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), data.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_token(tenant: dict[str, Any], *, secret: str, ttl_minutes: int) -> tuple[str, str]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64encode(
        json.dumps(
            {
                "sub": str(tenant["id"]),
                "username": tenant["username"],
                "tenant_id": int(tenant["id"]),
                "exp": int(expires_at.timestamp()),
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_sign(secret, signing_input)}", expires_at.isoformat()


def decode_token(token: str, *, secret: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    signing_input = f"{header}.{payload}"
    if not hmac.compare_digest(_sign(secret, signing_input), signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    try:
        claims = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if int(claims.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return claims


def current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict[str, Any]:
    claims = decode_token(credentials.credentials, secret=settings.jwt_secret)
    with db_session(settings.database_url) as conn:
        tenant = get_tenant(conn, int(claims["tenant_id"]))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant not found")
    user = dict(tenant)
    user.pop("password", None)
    return user
