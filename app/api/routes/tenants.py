from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.helpers import ensure_unique_username, parse_bool
from app.api.models import TenantPayload
from app.api.serializers import serialize_tenant
from app.config import settings
from app.core.auth import create_token, current_user
from app.database import (
    db_session,
    delete_tenant,
    get_tenant,
    list_tenants_page,
    set_active_tenant,
    upsert_tenant,
)
from app.runtime import restart_default_scheduler
from app.scheduler import build_scheduler


router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


@router.get("")
async def tenants(
    page: int = 1,
    page_size: int = 25,
    is_active: bool | None = Query(None),
    search: str | None = None,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        result = list_tenants_page(conn, page=page, page_size=page_size, is_active=parse_bool(is_active), search=search)
    result["items"] = [serialize_tenant(item) for item in result["items"]]
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tenant(payload: TenantPayload, _: dict[str, Any] = Depends(current_user)):
    if not (payload.password or "").strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password is required")
    with db_session(settings.database_url) as conn:
        ensure_unique_username(conn, payload.username)
        tenant_id = upsert_tenant(conn, tenant_id=None, **payload.model_dump())
        if payload.is_active:
            set_active_tenant(conn, tenant_id)
        tenant = get_tenant(conn, tenant_id)
    restart_default_scheduler(build_scheduler=build_scheduler, database_url=settings.database_url)
    return serialize_tenant(tenant)


@router.get("/{tenant_id}")
async def tenant(tenant_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_tenant(conn, tenant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return serialize_tenant(row)


@router.patch("/{tenant_id}")
async def update_tenant_route(tenant_id: int, payload: TenantPayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_tenant(conn, tenant_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
        ensure_unique_username(conn, payload.username, tenant_id)
        saved_id = upsert_tenant(conn, tenant_id=tenant_id, **payload.model_dump())
        if payload.is_active:
            set_active_tenant(conn, saved_id)
        row = get_tenant(conn, saved_id)
    restart_default_scheduler(build_scheduler=build_scheduler, database_url=settings.database_url)
    return serialize_tenant(row)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant_route(tenant_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_tenant(conn, tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{tenant_id}/activate")
async def activate_tenant(tenant_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_tenant(conn, tenant_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
        set_active_tenant(conn, tenant_id)
        row = get_tenant(conn, tenant_id)
    restart_default_scheduler(build_scheduler=build_scheduler, database_url=settings.database_url)
    token, expires_at = create_token(dict(row), secret=settings.jwt_secret, ttl_minutes=settings.jwt_ttl_minutes)
    return {"tenant": serialize_tenant(row), "access_token": token, "token_type": "bearer", "expires_at": expires_at}
