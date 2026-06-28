from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.models import ChatPolicyPayload
from app.config import settings
from app.core.auth import current_user
from app.database import db_session, get_tenant_group_chat, update_tenant_group_chat_policy
from app.services import list_known_tenant_group_chats, load_runtime_config, refresh_tenant_group_chats


router = APIRouter(prefix="/api/v1/chats", tags=["chats"])


@router.get("")
async def chats(
    include_blocked: bool = Query(True),
    user: dict[str, Any] = Depends(current_user),
):
    return list_known_tenant_group_chats(
        database_url=settings.database_url,
        tenant_id=int(user["id"]),
        include_blocked=include_blocked,
    )


@router.post("/refresh")
async def refresh_chats(user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    try:
        return await refresh_tenant_group_chats(settings=runtime, database_url=settings.database_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.patch("/{chat_id}/policy")
async def update_chat_policy(
    chat_id: str,
    payload: ChatPolicyPayload,
    user: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        if get_tenant_group_chat(conn, tenant_id=int(user["id"]), chat_id=chat_id) is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        try:
            update_tenant_group_chat_policy(conn, tenant_id=int(user["id"]), chat_id=chat_id, policy=payload.policy)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return get_tenant_group_chat(conn, tenant_id=int(user["id"]), chat_id=chat_id)
