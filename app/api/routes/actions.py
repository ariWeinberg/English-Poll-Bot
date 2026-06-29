from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.models import PreviewRequest, SendPollRequest, SendSummaryRequest
from app.config import settings
from app.core.auth import current_user
from app.database import create_incoming_webhook, db_session, get_app_config_json, now_iso, update_incoming_webhook, get_text
from app.scheduler import SCHEDULER_STATUS_KEY
from app.services import (
    extract_greenapi_webhook_metadata,
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
async def greenapi_webhook(tenant_id: int, request: Request):
    raw_body = (await request.body()).decode("utf-8")
    endpoint_path = f"/webhooks/greenapi/{tenant_id}"
    try:
        parsed_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        with db_session(settings.database_url) as conn:
            webhook_id = create_incoming_webhook(
                conn,
                tenant_id=tenant_id,
                provider="greenapi",
                endpoint_path=endpoint_path,
                payload_json=raw_body,
            )
            update_incoming_webhook(
                conn,
                webhook_id=webhook_id,
                decision_status="error",
                decision_reason="invalid_json",
                processed_at=now_iso(),
                error=f"Invalid JSON: {exc.msg}",
            )
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if not isinstance(parsed_payload, dict):
        with db_session(settings.database_url) as conn:
            webhook_id = create_incoming_webhook(
                conn,
                tenant_id=tenant_id,
                provider="greenapi",
                endpoint_path=endpoint_path,
                payload_json=raw_body,
            )
            update_incoming_webhook(
                conn,
                webhook_id=webhook_id,
                decision_status="error",
                decision_reason="invalid_payload",
                processed_at=now_iso(),
                error="Webhook payload must be a JSON object",
            )
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")

    metadata = extract_greenapi_webhook_metadata(parsed_payload)
    with db_session(settings.database_url) as conn:
        webhook_id = create_incoming_webhook(
            conn,
            tenant_id=tenant_id,
            provider="greenapi",
            endpoint_path=endpoint_path,
            payload_json=raw_body,
            type_webhook=metadata["type_webhook"],
            message_type=metadata["message_type"],
            greenapi_message_id=metadata["greenapi_message_id"],
        )
    try:
        decision = await handle_greenapi_webhook_async(
            database_url=settings.database_url,
            payload=parsed_payload,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        error_summary = str(exc).strip() or exc.__class__.__name__
        with db_session(settings.database_url) as conn:
            update_incoming_webhook(
                conn,
                webhook_id=webhook_id,
                type_webhook=metadata["type_webhook"],
                message_type=metadata["message_type"],
                greenapi_message_id=metadata["greenapi_message_id"],
                decision_status="error",
                decision_reason=error_summary,
                processed_at=now_iso(),
                error=error_summary,
            )
        raise

    with db_session(settings.database_url) as conn:
        update_incoming_webhook(
            conn,
            webhook_id=webhook_id,
            type_webhook=decision.type_webhook,
            message_type=decision.message_type,
            greenapi_message_id=decision.greenapi_message_id,
            poll_id=decision.poll_id,
            decision_status=decision.status,
            decision_reason=decision.reason,
            processed_at=now_iso(),
            error=decision.error,
        )
    return {"ok": True, "handled": decision.handled}
