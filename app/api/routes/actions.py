from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api.models import PreviewRequest, ReadinessDetail, ReadinessResponse, SendPollRequest, SendSummaryRequest
from app.config import settings
from app.core.auth import current_user
from app.database import (
    create_incoming_webhook,
    db_session,
    get_app_config_json,
    now_iso,
    update_incoming_webhook,
    get_text,
)
from app.greenapi import GreenAPIError
from app.scheduler import SCHEDULER_STATUS_KEY
from app.services import (
    extract_whatsapp_webhook_metadata,
    generate_and_send_poll,
    handle_greenapi_webhook_async,
    handle_waha_webhook_async,
    is_provider_error,
    load_runtime_config,
    preview_next_pooled_poll,
    send_pending_summaries,
    TextNotFoundError,
)
from app.waha import WAHAError


router = APIRouter(tags=["actions"])
READINESS_SCHEDULER_MAX_AGE_SECONDS = 180


@router.get("/api/v1/health")
async def health():
    with db_session(settings.database_url) as conn:
        scheduler_status = get_app_config_json(conn, key=SCHEDULER_STATUS_KEY)
    return {"ok": True, "scheduler": scheduler_status}


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _readiness_detail(
    *,
    ok: bool,
    detail: str,
    observed_at: str | None = None,
    last_tick_at: str | None = None,
    last_success_at: str | None = None,
    last_error: str | None = None,
) -> ReadinessDetail:
    return ReadinessDetail(
        ok=ok,
        detail=detail,
        observed_at=observed_at,
        last_tick_at=last_tick_at,
        last_success_at=last_success_at,
        last_error=last_error,
    )


def _build_readiness_payload(
    *,
    database_ok: bool,
    database_error: str | None,
    scheduler_status: dict[str, Any] | None,
    now_utc: datetime | None = None,
) -> tuple[ReadinessResponse, int]:
    current_time = now_utc or datetime.now(timezone.utc)
    observed_at = current_time.isoformat()
    database_detail = (
        "Database connection is available" if database_ok else database_error or "Database connection failed"
    )

    scheduler_ok = False
    scheduler_detail = "Scheduler heartbeat not recorded"
    scheduler_last_tick_at = None
    scheduler_last_success_at = None
    scheduler_last_error = None

    if isinstance(scheduler_status, dict):
        scheduler_last_tick_at = str(scheduler_status.get("last_tick_at") or "") or None
        scheduler_last_success_at = str(scheduler_status.get("last_success_at") or "") or None
        scheduler_last_error = str(scheduler_status.get("last_error") or "") or None
        tick_at = _parse_iso_datetime(scheduler_last_tick_at)
        success_at = _parse_iso_datetime(scheduler_last_success_at)
        if scheduler_last_error:
            scheduler_detail = "Scheduler reported a recent error"
        elif tick_at is None:
            scheduler_detail = "Scheduler heartbeat is missing a timestamp"
        elif success_at is None:
            scheduler_detail = "Scheduler has not recorded a successful tick yet"
        else:
            age_seconds = (current_time - tick_at).total_seconds()
            if age_seconds <= READINESS_SCHEDULER_MAX_AGE_SECONDS:
                scheduler_ok = True
                scheduler_detail = "Scheduler heartbeat is recent"
            else:
                scheduler_detail = "Scheduler heartbeat is stale"

    database_detail_obj = _readiness_detail(ok=database_ok, detail=database_detail, observed_at=observed_at)
    scheduler_detail_obj = _readiness_detail(
        ok=scheduler_ok,
        detail=scheduler_detail,
        observed_at=observed_at,
        last_tick_at=scheduler_last_tick_at,
        last_success_at=scheduler_last_success_at,
        last_error=scheduler_last_error,
    )
    payload = ReadinessResponse(
        ok=database_ok and scheduler_ok,
        generated_at=observed_at,
        database=database_detail_obj,
        scheduler=scheduler_detail_obj,
        warnings=[
            warning
            for warning in (
                None if database_ok else "Database connection is unavailable",
                None if scheduler_ok else scheduler_detail,
            )
            if warning
        ],
    )
    status_code = 200 if payload.ok else 503
    return payload, status_code


@router.get("/api/v1/readiness")
async def readiness():
    try:
        with db_session(settings.database_url) as conn:
            conn.execute("SELECT 1")
            scheduler_status = get_app_config_json(conn, key=SCHEDULER_STATUS_KEY)
    except Exception as exc:
        payload, _ = _build_readiness_payload(
            database_ok=False,
            database_error=exc.__class__.__name__,
            scheduler_status=None,
        )
        return JSONResponse(status_code=503, content=payload.model_dump())

    payload, status_code = _build_readiness_payload(
        database_ok=True,
        database_error=None,
        scheduler_status=scheduler_status,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


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
    try:
        poll_id = await generate_and_send_poll(
            settings=runtime,
            database_url=settings.database_url,
            text_id=payload.text_id,
            scheduled_slot=payload.scheduled_slot,
        )
    except TextNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (WAHAError, GreenAPIError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        if is_provider_error(exc):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise
    return {"poll_id": poll_id}


@router.post("/api/v1/summaries/send-now")
async def summary_now(payload: SendSummaryRequest, user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    count = await send_pending_summaries(settings=runtime, database_url=settings.database_url, text_id=payload.text_id)
    return {"sent": count}


@router.post("/webhooks/greenapi/{tenant_id}")
async def greenapi_webhook(tenant_id: int, request: Request):
    return await _provider_webhook(tenant_id=tenant_id, provider="greenapi", request=request)


@router.post("/webhooks/waha/{tenant_id}")
async def waha_webhook(tenant_id: int, request: Request):
    return await _provider_webhook(tenant_id=tenant_id, provider="waha", request=request)


async def _provider_webhook(*, tenant_id: int, provider: str, request: Request):
    raw_body = (await request.body()).decode("utf-8")
    endpoint_path = f"/webhooks/{provider}/{tenant_id}"
    try:
        parsed_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        with db_session(settings.database_url) as conn:
            webhook_id = create_incoming_webhook(
                conn,
                tenant_id=tenant_id,
                provider=provider,
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
                provider=provider,
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

    metadata = extract_whatsapp_webhook_metadata(parsed_payload, provider=provider)
    with db_session(settings.database_url) as conn:
        webhook_id = create_incoming_webhook(
            conn,
            tenant_id=tenant_id,
            provider=provider,
            endpoint_path=endpoint_path,
            payload_json=raw_body,
            type_webhook=metadata["type_webhook"],
            message_type=metadata["message_type"],
            provider_message_id=metadata["provider_message_id"],
            greenapi_message_id=metadata["greenapi_message_id"],
            provider_metadata=metadata["provider_metadata"],
        )
    try:
        if provider == "waha":
            decision = await handle_waha_webhook_async(
                database_url=settings.database_url,
                payload=parsed_payload,
                tenant_id=tenant_id,
            )
        else:
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
                provider_message_id=metadata["provider_message_id"],
                greenapi_message_id=metadata["greenapi_message_id"],
                provider_metadata=metadata["provider_metadata"],
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
            provider_message_id=decision.provider_message_id,
            greenapi_message_id=decision.greenapi_message_id,
            provider_metadata=decision.provider_metadata,
            poll_id=decision.poll_id,
            decision_status=decision.status,
            decision_reason=decision.reason,
            processed_at=now_iso(),
            error=decision.error,
        )
    return {"ok": True, "handled": decision.handled}
