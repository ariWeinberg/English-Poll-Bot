from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.models import PollVotePayload
from app.config import settings
from app.core.auth import current_user
from app.database import (
    create_poll_vote,
    db_session,
    delete_poll_vote,
    get_poll_vote,
    get_poll_vote_event,
    list_poll_vote_events_page,
    list_poll_votes_page,
    update_poll_vote,
)


router = APIRouter(tags=["votes"])


@router.get("/api/v1/poll-votes")
async def poll_votes(
    page: int = 1,
    page_size: int = 25,
    poll_id: int | None = None,
    option_name: str | None = None,
    voter_wid: str | None = None,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        return list_poll_votes_page(
            conn,
            page=page,
            page_size=page_size,
            poll_id=poll_id,
            option_name=option_name,
            voter_wid=voter_wid,
        )


@router.get("/api/v1/poll-vote-events")
async def poll_vote_events(
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    poll_id: int | None = None,
    option_name: str | None = None,
    voter_wid: str | None = None,
    user: dict[str, Any] = Depends(current_user),
):
    scoped_tenant = tenant_id if tenant_id is not None else int(user["id"])
    with db_session(settings.database_url) as conn:
        return list_poll_vote_events_page(
            conn,
            page=page,
            page_size=page_size,
            tenant_id=scoped_tenant,
            poll_id=poll_id,
            option_name=option_name,
            voter_wid=voter_wid,
        )


@router.post("/api/v1/poll-votes", status_code=status.HTTP_201_CREATED)
async def create_vote(payload: PollVotePayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        vote_id = create_poll_vote(conn, **payload.model_dump())
        return get_poll_vote(conn, vote_id)


@router.get("/api/v1/poll-votes/{vote_id}")
async def poll_vote(vote_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_poll_vote(conn, vote_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poll vote not found")
    return row


@router.get("/api/v1/poll-vote-events/{event_id}")
async def poll_vote_event(event_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_poll_vote_event(conn, event_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poll vote event not found")
    return row


@router.patch("/api/v1/poll-votes/{vote_id}")
async def update_vote(vote_id: int, payload: PollVotePayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_poll_vote(conn, vote_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poll vote not found")
        update_poll_vote(conn, vote_id=vote_id, **payload.model_dump())
        return get_poll_vote(conn, vote_id)


@router.delete("/api/v1/poll-votes/{vote_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vote(vote_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_poll_vote(conn, vote_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
