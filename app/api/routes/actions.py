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
    get_tenant,
    get_incoming_webhook,
    now_iso,
    get_text,
    list_polls,
    list_texts,
    poll_quality_summary,
    update_incoming_webhook,
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


def _build_pilot_readiness_payload(
    *,
    connector_ready: bool,
    gemini_ready: bool,
    enabled_text_count: int,
    active_poll_rule_count: int,
    sent_poll_count: int,
    scheduler_ok: bool,
    observed_at: str,
) -> tuple[dict[str, Any], int]:
    items = [
        {
            "label": "Connector configured",
            "ready": connector_ready and gemini_ready,
            "detail": "WhatsApp connector and Gemini settings are ready."
            if connector_ready and gemini_ready
            else "Finish connector or Gemini setup in Workspace Settings.",
        },
        {
            "label": "Live content available",
            "ready": enabled_text_count > 0,
            "detail": (
                f"{enabled_text_count} enabled text{'s' if enabled_text_count != 1 else ''} are ready to schedule."
                if enabled_text_count > 0
                else "Add and enable at least one text before launch."
            ),
        },
        {
            "label": "Poll rules assigned",
            "ready": active_poll_rule_count > 0,
            "detail": (
                f"{active_poll_rule_count} active poll rule{'s' if active_poll_rule_count != 1 else ''} are attached to enabled texts."
                if active_poll_rule_count > 0
                else "Assign or enable a poll schedule rule before launch."
            ),
        },
        {
            "label": "Delivery history present",
            "ready": sent_poll_count > 0,
            "detail": (
                f"{sent_poll_count} sent poll{'s' if sent_poll_count != 1 else ''} show the delivery path is working."
                if sent_poll_count > 0
                else "Send at least one poll so pilot monitoring has a baseline."
            ),
        },
        {
            "label": "Platform readiness",
            "ready": scheduler_ok,
            "detail": "Database and scheduler readiness checks are fresh."
            if scheduler_ok
            else "Resolve the release readiness check before starting a pilot.",
        },
    ]
    warnings = [
        warning
        for warning in (
            None if connector_ready and gemini_ready else "Workspace integration is incomplete",
            None if enabled_text_count > 0 else "No enabled texts are available",
            None if active_poll_rule_count > 0 else "No active poll rules are attached",
            None if sent_poll_count > 0 else "No sent polls exist yet",
            None if scheduler_ok else "Release readiness check is not passing",
        )
        if warning
    ]
    ok = all(item["ready"] for item in items)
    payload = {
        "ok": ok,
        "generated_at": observed_at,
        "items": items,
        "warnings": warnings,
    }
    return payload, 200 if ok else 503


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


@router.get("/api/v1/pilot-readiness")
async def pilot_readiness(user: dict[str, Any] = Depends(current_user)):
    observed_at = datetime.now(timezone.utc).isoformat()
    with db_session(settings.database_url) as conn:
        tenant = get_tenant(conn, int(user["id"]))
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        texts = list_texts(conn, tenant_id=int(user["id"]))
        sent_polls = list_polls(conn, limit=10000, tenant_id=int(user["id"]), status="sent")
        poll_rule_count = sum(
            1
            for text in texts
            for rule in text.get("schedule_rules", [])
            if rule.get("enabled") and rule.get("delivery_type") == "poll"
        )
        scheduler_status = get_app_config_json(conn, key=SCHEDULER_STATUS_KEY)
    readiness_payload, _ = _build_readiness_payload(
        database_ok=True,
        database_error=None,
        scheduler_status=scheduler_status,
        now_utc=datetime.now(timezone.utc),
    )
    payload, status_code = _build_pilot_readiness_payload(
        connector_ready=bool((tenant.get("whatsapp_connector") or {}).get("provider")),
        gemini_ready=bool(str(tenant.get("gemini_api_key") or "").strip()),
        enabled_text_count=sum(1 for text in texts if text.get("enabled")),
        active_poll_rule_count=poll_rule_count,
        sent_poll_count=len(sent_polls),
        scheduler_ok=readiness_payload.ok,
        observed_at=observed_at,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/api/v1/pilot-report.json")
async def pilot_report(user: dict[str, Any] = Depends(current_user)):
    observed_at = datetime.now(timezone.utc).isoformat()
    with db_session(settings.database_url) as conn:
        tenant = get_tenant(conn, int(user["id"]))
        if tenant is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        texts = list_texts(conn, tenant_id=int(user["id"]))
        sent_polls = list_polls(conn, limit=10000, tenant_id=int(user["id"]), status="sent")
        poll_rule_count = sum(
            1
            for text in texts
            for rule in text.get("schedule_rules", [])
            if rule.get("enabled") and rule.get("delivery_type") == "poll"
        )
        readiness_status = get_app_config_json(conn, key=SCHEDULER_STATUS_KEY)
        quality_summary = poll_quality_summary(conn, tenant_id=int(user["id"]))

    readiness_payload, _ = _build_readiness_payload(
        database_ok=True,
        database_error=None,
        scheduler_status=readiness_status,
        now_utc=datetime.now(timezone.utc),
    )
    pilot_readiness_payload, _ = _build_pilot_readiness_payload(
        connector_ready=bool((tenant.get("whatsapp_connector") or {}).get("provider")),
        gemini_ready=bool(str(tenant.get("gemini_api_key") or "").strip()),
        enabled_text_count=sum(1 for text in texts if text.get("enabled")),
        active_poll_rule_count=poll_rule_count,
        sent_poll_count=len(sent_polls),
        scheduler_ok=readiness_payload.ok,
        observed_at=observed_at,
    )
    warnings = list(pilot_readiness_payload["warnings"])
    if int(quality_summary["review_required_count"]) > 0:
        warnings.append(f"Question review is required for {int(quality_summary['review_required_count'])} polls")
    if int(quality_summary["low_accuracy_count"]) > 0:
        warnings.append(f"{int(quality_summary['low_accuracy_count'])} polls are showing low accuracy")

    payload = {
        "generated_at": observed_at,
        "tenant": {
            "id": int(tenant["id"]),
            "name": str(tenant["name"]),
            "username": str(tenant["username"]),
            "timezone": str(tenant["timezone"]),
            "scheduler_enabled": bool(tenant["scheduler_enabled"]),
            "summary_enabled": bool(tenant["summary_enabled"]),
            "whatsapp_provider": str(tenant.get("whatsapp_provider") or ""),
            "connector_configured": bool((tenant.get("whatsapp_connector") or {}).get("provider")),
            "gemini_configured": bool(str(tenant.get("gemini_api_key") or "").strip()),
        },
        "metrics": {
            "text_count": len(texts),
            "enabled_text_count": sum(1 for text in texts if text.get("enabled")),
            "active_poll_rule_count": poll_rule_count,
            "sent_poll_count": len(sent_polls),
            "total_poll_count": int(quality_summary["total_polls"]),
            "review_required_count": int(quality_summary["review_required_count"]),
            "unanswered_count": int(quality_summary["unanswered_count"]),
            "low_accuracy_count": int(quality_summary["low_accuracy_count"]),
        },
        "readiness": pilot_readiness_payload,
        "quality": {
            "draft_count": int(quality_summary["draft_count"]),
            "approved_count": int(quality_summary["approved_count"]),
            "needs_edit_count": int(quality_summary["needs_edit_count"]),
            "disabled_count": int(quality_summary["disabled_count"]),
            "archived_count": int(quality_summary["archived_count"]),
            "review_required_count": int(quality_summary["review_required_count"]),
            "unanswered_count": int(quality_summary["unanswered_count"]),
            "low_accuracy_count": int(quality_summary["low_accuracy_count"]),
        },
        "warnings": warnings,
    }
    return JSONResponse(
        status_code=200,
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="pilot-report.json"'},
    )


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


@router.post("/api/v1/webhooks/{webhook_id}/retry")
async def retry_webhook(webhook_id: int, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_incoming_webhook(conn, tenant_id=int(user["id"]), webhook_id=webhook_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Webhook event not found")
    if row.get("decision_status") == "accepted":
        raise HTTPException(status_code=409, detail="Accepted webhooks cannot be retried")
    current_retry_count = int(row.get("retry_count") or 0)

    raw_payload = str(row.get("payload_json") or "")
    try:
        parsed_payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        with db_session(settings.database_url) as conn:
            update_incoming_webhook(
                conn,
                webhook_id=webhook_id,
                retry_count=current_retry_count + 1,
                last_retry_at=now_iso(),
                last_retry_error=f"Invalid JSON: {exc.msg}",
                error=f"Invalid JSON: {exc.msg}",
            )
        raise HTTPException(status_code=400, detail="Stored webhook payload is invalid JSON") from exc
    if not isinstance(parsed_payload, dict):
        with db_session(settings.database_url) as conn:
            update_incoming_webhook(
                conn,
                webhook_id=webhook_id,
                retry_count=current_retry_count + 1,
                last_retry_at=now_iso(),
                last_retry_error="Webhook payload must be a JSON object",
                error="Webhook payload must be a JSON object",
            )
        raise HTTPException(status_code=400, detail="Stored webhook payload must be a JSON object")

    metadata = extract_whatsapp_webhook_metadata(parsed_payload, provider=str(row.get("provider") or "greenapi"))
    await _process_provider_webhook(
        webhook_id=webhook_id,
        tenant_id=int(user["id"]),
        provider=str(row.get("provider") or "greenapi"),
        parsed_payload=parsed_payload,
        metadata=metadata,
        retry=True,
    )
    return {"ok": True, "retried": True}


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
    await _process_provider_webhook(
        webhook_id=webhook_id,
        tenant_id=tenant_id,
        provider=provider,
        parsed_payload=parsed_payload,
        metadata=metadata,
        retry=False,
    )
    return {"ok": True, "handled": True}


async def _process_provider_webhook(
    *,
    webhook_id: int,
    tenant_id: int,
    provider: str,
    parsed_payload: dict[str, Any],
    metadata: dict[str, Any],
    retry: bool,
):
    with db_session(settings.database_url) as conn:
        current_retry_count = int(
            (get_incoming_webhook(conn, tenant_id=tenant_id, webhook_id=webhook_id) or {}).get("retry_count", 0)
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
                retry_count=current_retry_count + (1 if retry else 0),
                last_retry_at=now_iso() if retry else None,
                last_retry_error=error_summary if retry else None,
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
            retry_count=current_retry_count + (1 if retry else 0),
            last_retry_at=now_iso() if retry else None,
            last_retry_error=None if retry else None,
            error=decision.error,
        )
    return {"ok": True, "handled": decision.handled}
