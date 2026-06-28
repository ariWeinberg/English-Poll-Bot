from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.models import ScheduleRulePayload, ScheduleRuleUpdatePayload
from app.config import settings
from app.core.auth import current_user
from app.database import (
    create_schedule_rule,
    db_session,
    delete_schedule_rule,
    get_schedule_rule,
    list_schedule_rules,
    update_schedule_rule,
)


router = APIRouter(prefix="/api/v1/schedule-rules", tags=["schedule-rules"])


@router.get("")
async def schedule_rules(user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        return list_schedule_rules(conn, tenant_id=int(user["id"]))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_schedule_rule_route(payload: ScheduleRulePayload, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        try:
            rule_id = create_schedule_rule(conn, tenant_id=int(user["id"]), **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return get_schedule_rule(conn, tenant_id=int(user["id"]), rule_id=rule_id)


@router.get("/{rule_id}")
async def schedule_rule(rule_id: int, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_schedule_rule(conn, tenant_id=int(user["id"]), rule_id=rule_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule rule not found")
    return row


@router.patch("/{rule_id}")
async def update_schedule_rule_route(
    rule_id: int,
    payload: ScheduleRuleUpdatePayload,
    user: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        existing = get_schedule_rule(conn, tenant_id=int(user["id"]), rule_id=rule_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule rule not found")
        merged = {
            key: value
            for key, value in {**existing, **payload.model_dump(exclude_unset=True)}.items()
            if key
            in {
                "name",
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
            update_schedule_rule(conn, tenant_id=int(user["id"]), rule_id=rule_id, **merged)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return get_schedule_rule(conn, tenant_id=int(user["id"]), rule_id=rule_id)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule_rule_route(rule_id: int, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        existing = get_schedule_rule(conn, tenant_id=int(user["id"]), rule_id=rule_id)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule rule not found")
        delete_schedule_rule(conn, tenant_id=int(user["id"]), rule_id=rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
