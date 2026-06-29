from __future__ import annotations

from fastapi import HTTPException, status

from app.database import get_tenant_by_username


def ensure_unique_username(conn: object, username: str, current_tenant_id: int | None = None) -> None:
    existing = get_tenant_by_username(conn, username)
    if existing is None:
        return
    if current_tenant_id is not None and int(existing["id"]) == current_tenant_id:
        return
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")


def parse_bool(value: bool | None) -> bool | None:
    return value
