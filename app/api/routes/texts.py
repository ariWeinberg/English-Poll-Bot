from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from pydantic import ValidationError

from app.api.files import save_attachment
from app.api.helpers import parse_bool
from app.api.models import RosterMemberUpdatePayload, ScheduleRulePayload, ScheduleRuleUpdatePayload, TextPayload
from app.config import settings
from app.core.auth import current_user
from app.database import (
    create_text_schedule_rule,
    db_session,
    delete_text_schedule_rule,
    delete_text,
    get_text,
    get_text_schedule_rule,
    list_chat_participants,
    list_text_schedule_rules,
    list_texts_page,
    update_text_schedule_rule,
    update_chat_participant_exclusion,
    upsert_text,
)
from app.services import load_runtime_config, sync_text_roster


router = APIRouter(prefix="/api/v1/texts", tags=["texts"])


@router.get("")
async def texts(
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    enabled: bool | None = Query(None),
    search: str | None = None,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        return list_texts_page(
            conn,
            page=page,
            page_size=page_size,
            tenant_id=tenant_id,
            enabled=parse_bool(enabled),
            search=search,
        )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_text(
    tenant_id: int = Form(...),
    title: str = Form(...),
    body: str = Form(...),
    chat_id: str = Form(...),
    schedule_rules_json: str | None = Form(None),
    poll_pool_threshold_percent: int | None = Form(None),
    enabled: bool = Form(True),
    attachment: UploadFile | None = File(None),
    _: dict[str, Any] = Depends(current_user),
):
    attachment_name, attachment_path = await save_attachment(attachment)
    schedule_rules: list[dict[str, Any]] | None = None
    if schedule_rules_json and schedule_rules_json.strip():
        try:
            payload = json.loads(schedule_rules_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="schedule_rules_json must be valid JSON"
            ) from exc
        if not isinstance(payload, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="schedule_rules_json must be a JSON array"
            )
        try:
            schedule_rules = [ScheduleRulePayload.model_validate(item).model_dump() for item in payload]
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc
    with db_session(settings.database_url) as conn:
        try:
            text_id = upsert_text(
                conn,
                text_id=None,
                tenant_id=tenant_id,
                title=title,
                body=body,
                chat_id=chat_id,
                poll_pool_threshold_percent=poll_pool_threshold_percent,
                enabled=enabled,
                attachment_name=attachment_name,
                attachment_path=attachment_path,
                schedule_rules=schedule_rules,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return get_text(conn, text_id)


@router.get("/{text_id}")
async def text(text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_text(conn, text_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found")
    return row


@router.patch("/{text_id}")
async def update_text_route(payload: TextPayload, text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_text(conn, text_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found")
        try:
            upsert_text(conn, text_id=text_id, attachment_name=None, attachment_path=None, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return get_text(conn, text_id)


@router.get("/{text_id}/schedule-rules")
async def text_schedule_rules(text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_text(conn, text_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found")
        return list_text_schedule_rules(conn, text_id=text_id)


@router.post("/{text_id}/schedule-rules", status_code=status.HTTP_201_CREATED)
async def create_text_schedule_rule_route(
    text_id: int,
    payload: ScheduleRulePayload,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        if get_text(conn, text_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found")
        try:
            rule_id = create_text_schedule_rule(conn, text_id=text_id, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        rule = get_text_schedule_rule(conn, text_id=text_id, rule_id=rule_id)
    return rule


@router.patch("/{text_id}/schedule-rules/{rule_id}")
async def update_text_schedule_rule_route(
    text_id: int,
    rule_id: int,
    payload: ScheduleRuleUpdatePayload,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        existing = get_text_schedule_rule(conn, text_id=text_id, rule_id=rule_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule rule not found")
        merged = {
            key: value
            for key, value in {**existing, **payload.model_dump(exclude_unset=True)}.items()
            if key
            in {
                "delivery_type",
                "rule_type",
                "enabled",
                "time",
                "weekdays",
                "month_dates",
                "window_start",
                "window_end",
                "count_mode",
                "count_value",
                "count_min",
                "count_max",
                "label",
            }
        }
        try:
            update_text_schedule_rule(conn, text_id=text_id, rule_id=rule_id, **merged)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return get_text_schedule_rule(conn, text_id=text_id, rule_id=rule_id)


@router.delete("/{text_id}/schedule-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_text_schedule_rule_route(text_id: int, rule_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        existing = get_text_schedule_rule(conn, text_id=text_id, rule_id=rule_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule rule not found")
        delete_text_schedule_rule(conn, text_id=text_id, rule_id=rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{text_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_text_route(text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_text(conn, text_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{text_id}/roster")
async def text_roster(text_id: int, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        text = get_text(conn, text_id)
        if text is None or int(text["tenant_id"]) != int(user["id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found")
        items = list_chat_participants(conn, tenant_id=int(user["id"]), chat_id=str(text["chat_id"]))
    active_count = sum(1 for item in items if item["is_active_in_chat"])
    excluded_count = sum(1 for item in items if item["excluded_from_coverage"])
    last_synced_at = items[0]["last_synced_at"] if items else None
    return {
        "text_id": text_id,
        "chat_id": text["chat_id"],
        "last_synced_at": last_synced_at,
        "active_count": active_count,
        "excluded_count": excluded_count,
        "items": items,
    }


@router.post("/{text_id}/roster/sync")
async def sync_text_roster_route(text_id: int, user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    try:
        return await sync_text_roster(settings=runtime, database_url=settings.database_url, text_id=text_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.patch("/{text_id}/roster/{voter_wid}")
async def update_text_roster_member(
    text_id: int,
    voter_wid: str,
    payload: RosterMemberUpdatePayload,
    user: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        text = get_text(conn, text_id)
        if text is None or int(text["tenant_id"]) != int(user["id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Text not found")
        try:
            update_chat_participant_exclusion(
                conn,
                tenant_id=int(user["id"]),
                chat_id=str(text["chat_id"]),
                voter_wid=voter_wid,
                excluded_from_coverage=payload.excluded_from_coverage,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        items = list_chat_participants(conn, tenant_id=int(user["id"]), chat_id=str(text["chat_id"]))
        updated = next((item for item in items if str(item["voter_wid"]) == voter_wid), None)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Roster member not found")
    return updated
