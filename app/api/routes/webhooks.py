from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.models import WebhookEvent, WebhookEventPage
from app.config import settings
from app.core.auth import current_user
from app.database import db_session, get_incoming_webhook, list_incoming_webhooks_page


router = APIRouter(tags=["webhooks"])


@router.get("/api/v1/webhooks", response_model=WebhookEventPage)
async def webhook_events(
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    reason: str | None = None,
    type_webhook: str | None = None,
    provider_message_id: str | None = None,
    greenapi_message_id: str | None = None,
    poll_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        return list_incoming_webhooks_page(
            conn,
            tenant_id=int(user["id"]),
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            reason=reason,
            type_webhook=type_webhook,
            provider_message_id=provider_message_id,
            greenapi_message_id=greenapi_message_id,
            poll_id=poll_id,
            date_from=date_from,
            date_to=date_to,
        )


@router.get("/api/v1/webhooks/{id}", response_model=WebhookEvent)
async def webhook_event(id: int, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_incoming_webhook(conn, tenant_id=int(user["id"]), webhook_id=id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook event not found")
    return row
