from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.core.auth import current_user
from app.database import (
    db_session,
    get_learner_summary,
    get_learners_summary,
    list_learner_history,
    list_learner_missed_polls,
    list_learners_page,
)


router = APIRouter(prefix="/api/v1/learners", tags=["learners"])


def _scoped_tenant_id(requested_tenant_id: int | None, user: dict[str, Any]) -> int:
    current_tenant_id = int(user["id"])
    if requested_tenant_id is None:
        return current_tenant_id
    if requested_tenant_id != current_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant access denied")
    return requested_tenant_id


@router.get("")
async def learners(
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    segment: str = "all",
    sort_by: str = "latest_activity",
    sort_dir: str = "desc",
    user: dict[str, Any] = Depends(current_user),
):
    scoped_tenant = _scoped_tenant_id(tenant_id, user)
    with db_session(settings.database_url) as conn:
        return list_learners_page(
            conn,
            tenant_id=scoped_tenant,
            page=page,
            page_size=page_size,
            text_id=text_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
            segment=segment,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )


@router.get("/summary")
async def learners_summary(
    tenant_id: int | None = None,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict[str, Any] = Depends(current_user),
):
    scoped_tenant = _scoped_tenant_id(tenant_id, user)
    with db_session(settings.database_url) as conn:
        return get_learners_summary(
            conn,
            tenant_id=scoped_tenant,
            text_id=text_id,
            date_from=date_from,
            date_to=date_to,
        )


@router.get("/{voter_wid}")
async def learner_detail(
    voter_wid: str,
    tenant_id: int | None = None,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    history_limit: int = 25,
    missed_limit: int = 25,
    user: dict[str, Any] = Depends(current_user),
):
    scoped_tenant = _scoped_tenant_id(tenant_id, user)
    with db_session(settings.database_url) as conn:
        learner = get_learner_summary(
            conn,
            tenant_id=scoped_tenant,
            voter_wid=voter_wid,
            text_id=text_id,
            date_from=date_from,
            date_to=date_to,
        )
        if learner is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found")
        history = list_learner_history(
            conn,
            tenant_id=scoped_tenant,
            voter_wid=voter_wid,
            text_id=text_id,
            date_from=date_from,
            date_to=date_to,
            limit=history_limit,
        )
        missed_polls = list_learner_missed_polls(
            conn,
            tenant_id=scoped_tenant,
            voter_wid=voter_wid,
            text_id=text_id,
            date_from=date_from,
            date_to=date_to,
            limit=missed_limit,
        )
    return {"learner": learner, "history": history, "missed_polls": missed_polls}
