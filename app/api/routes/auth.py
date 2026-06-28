from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.helpers import ensure_unique_username
from app.api.models import LoginRequest, RegisterRequest, TokenResponse
from app.auth import verify_password
from app.config import settings
from app.core.auth import create_token, current_user
from app.database import db_session, get_tenant, get_tenant_by_username, set_active_tenant, upsert_tenant
from app.runtime import restart_default_scheduler
from app.scheduler import build_scheduler


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    with db_session(settings.database_url) as conn:
        tenant = get_tenant_by_username(conn, payload.username)
    if tenant is None or not verify_password(payload.password.strip(), str(tenant["password"] or "")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token, expires_at = create_token(dict(tenant), secret=settings.jwt_secret, ttl_minutes=settings.jwt_ttl_minutes)
    return TokenResponse(access_token=token, expires_at=expires_at)


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return user


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest):
    with db_session(settings.database_url) as conn:
        ensure_unique_username(conn, payload.username)
        tenant_id = upsert_tenant(
            conn,
            tenant_id=None,
            name=payload.name,
            username=payload.username,
            password=payload.password,
            greenapi_api_url="https://api.green-api.com",
            greenapi_id_instance="",
            greenapi_api_token_instance="",
            gemini_api_key="",
            gemini_model="gemini-3.5-flash",
            timezone=payload.timezone,
            summary_enabled=True,
            scheduler_enabled=True,
            is_active=True,
        )
        set_active_tenant(conn, tenant_id)
        tenant = get_tenant(conn, tenant_id)
    restart_default_scheduler(build_scheduler=build_scheduler, database_url=settings.database_url)
    token, expires_at = create_token(dict(tenant), secret=settings.jwt_secret, ttl_minutes=settings.jwt_ttl_minutes)
    return TokenResponse(access_token=token, expires_at=expires_at)
