from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.openapi.docs import get_swagger_ui_html

from app.api.models import DocsSessionResponse
from app.config import settings
from app.core.auth import current_user
from app.core.docs import create_docs_token, decode_docs_token


router = APIRouter(prefix="/api/v1", tags=["docs"])


@router.post("/docs/session", response_model=DocsSessionResponse)
async def create_docs_session(user: dict = Depends(current_user)):
    docs_token, expires_at = create_docs_token(
        secret=settings.jwt_secret,
        tenant_id=int(user["id"]),
        username=str(user["username"]),
        ttl_seconds=settings.docs_token_ttl_seconds,
    )
    return DocsSessionResponse(
        docs_token=docs_token,
        expires_at=expires_at,
        docs_url=f"/api/v1/docs?token={docs_token}",
        openapi_url=f"/api/v1/openapi.json?token={docs_token}",
    )


@router.get("/docs", include_in_schema=False)
async def protected_docs(token: str = Query(...)):
    decode_docs_token(token, secret=settings.jwt_secret)
    return get_swagger_ui_html(
        openapi_url=f"/api/v1/openapi.json?token={token}",
        title="English WhatsApp Poll Bot API - Swagger UI",
    )


@router.get("/openapi.json", include_in_schema=False)
async def protected_openapi(request: Request, token: str = Query(...)):
    decode_docs_token(token, secret=settings.jwt_secret)
    return request.app.openapi()
