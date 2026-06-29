from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.models import PreviewRequest, SendPollRequest, SendSummaryRequest
from app.config import settings
from app.core.auth import current_user
from app.database import db_session, get_app_config_json, get_text
from app.scheduler import SCHEDULER_STATUS_KEY
from app.services import (
    generate_and_send_poll,
    handle_greenapi_webhook_async,
    load_runtime_config,
    preview_next_pooled_poll,
    send_pending_summaries,
)


router = APIRouter(tags=["actions"])


@router.get("/api/v1/health")
async def health():
    with db_session(settings.database_url) as conn:
        scheduler_status = get_app_config_json(conn, key=SCHEDULER_STATUS_KEY)
    return {"ok": True, "scheduler": scheduler_status}


@router.post("/api/v1/questions/preview")
async def preview_question(payload: PreviewRequest, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        text_row = get_text(conn, payload.text_id)
    if text_row is None:
        raise HTTPException(status_code=404, detail="Text not found")
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    return await preview_next_pooled_poll(settings=runtime, database_url=settings.database_url, text_id=payload.text_id)


@router.post("/api/v1/polls/send-now")
async def send_now(payload: SendPollRequest, user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    poll_id = await generate_and_send_poll(
        settings=runtime,
        database_url=settings.database_url,
        text_id=payload.text_id,
        scheduled_slot=payload.scheduled_slot,
    )
    return {"poll_id": poll_id}


@router.post("/api/v1/summaries/send-now")
async def summary_now(payload: SendSummaryRequest, user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    count = await send_pending_summaries(settings=runtime, database_url=settings.database_url, text_id=payload.text_id)
    return {"sent": count}


@router.post("/webhooks/greenapi/{tenant_id}")
async def greenapi_webhook(tenant_id: int, payload: dict[str, Any]):
    handled = await handle_greenapi_webhook_async(
        database_url=settings.database_url, payload=payload, tenant_id=tenant_id
    )
    return {"ok": True, "handled": handled}
