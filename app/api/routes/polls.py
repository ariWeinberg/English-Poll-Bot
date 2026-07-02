from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status as http_status

from app.api.models import PollPayload, PollRankPayload
from app.api.serializers import serialize_poll
from app.config import settings
from app.core.auth import current_user
from app.database import (
    all_poll_stats,
    count_queued_polls,
    create_poll,
    db_session,
    delete_poll,
    export_stats_csv,
    get_effective_poll_pool_policy,
    get_poll_coverage_page,
    get_poll,
    get_text,
    list_poll_vote_status,
    list_polls_page,
    list_queued_polls,
    poll_quality_summary,
    reorder_queued_poll,
    update_poll,
)
from app.services import fill_poll_pool, load_runtime_config


router = APIRouter(tags=["polls"])


@router.get("/api/v1/polls")
async def polls(
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    text_id: int | None = None,
    status: str | None = None,
    review_status: str | None = None,
    scheduled_slot: str | None = None,
    sent_from: str | None = None,
    sent_to: str | None = None,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        result = list_polls_page(
            conn,
            page=page,
            page_size=page_size,
            tenant_id=tenant_id,
            text_id=text_id,
            status=status,
            review_status=review_status,
            scheduled_slot=scheduled_slot,
            sent_from=sent_from,
            sent_to=sent_to,
        )
    result["items"] = [serialize_poll(item) for item in result["items"]]
    return result


@router.get("/api/v1/polls/quality-summary")
async def poll_quality_summary_route(
    tenant_id: int | None = None,
    text_id: int | None = None,
    status: str | None = None,
    sent_from: str | None = None,
    sent_to: str | None = None,
    user: dict[str, Any] = Depends(current_user),
):
    scoped_tenant = tenant_id if tenant_id is not None else int(user["id"])
    if tenant_id is not None and tenant_id != int(user["id"]):
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Tenant access denied")
    with db_session(settings.database_url) as conn:
        return poll_quality_summary(
            conn,
            tenant_id=scoped_tenant,
            text_id=text_id,
            status=status,
            date_from=sent_from,
            date_to=sent_to,
        )


@router.post("/api/v1/polls", status_code=http_status.HTTP_201_CREATED)
async def create_poll_route(payload: PollPayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        poll_id = create_poll(
            conn,
            tenant_id=payload.tenant_id,
            text_id=payload.text_id,
            question=payload.question,
            options=payload.options,
            correct_option=payload.correct_option,
            explanation=payload.explanation,
            chat_id=payload.chat_id,
            generated_from_text=payload.generated_from_text,
            scheduled_slot=payload.scheduled_slot,
            status=payload.status,
            review_status=payload.review_status,
            review_notes=payload.review_notes,
            pool_rank=payload.pool_rank,
            change_window_seconds=payload.change_window_seconds,
            manual_lock=payload.manual_lock,
            auto_lock_seconds=payload.auto_lock_seconds,
        )
        update_poll(conn, poll_id=poll_id, **payload.model_dump())
        return serialize_poll(get_poll(conn, poll_id))


@router.get("/api/v1/polls/stats")
async def poll_stats_route(
    tenant_id: int | None = None,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 25,
    user: dict[str, Any] = Depends(current_user),
):
    scoped_tenant = int(user["id"])
    if tenant_id is not None and tenant_id != scoped_tenant:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Tenant access denied")
    with db_session(settings.database_url) as conn:
        return all_poll_stats(
            conn,
            limit=limit,
            tenant_id=scoped_tenant,
            text_id=text_id,
            date_from=date_from,
            date_to=date_to,
        )


@router.get("/api/v1/polls/export.csv")
async def export_csv(tenant_id: int | None = None, user: dict[str, Any] = Depends(current_user)):
    scoped_tenant = tenant_id if tenant_id is not None else int(user["id"])
    with db_session(settings.database_url) as conn:
        csv_text = export_stats_csv(conn, tenant_id=scoped_tenant)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=poll-stats.csv"},
    )


@router.get("/api/v1/polls/{poll_id}")
async def poll(poll_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_poll(conn, poll_id)
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Poll not found")
    return serialize_poll(row)


@router.get("/api/v1/polls/{poll_id}/vote-status")
async def poll_vote_status(poll_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_poll(conn, poll_id) is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Poll not found")
        return list_poll_vote_status(conn, poll_id=poll_id)


@router.get("/api/v1/polls/{poll_id}/coverage")
async def poll_coverage(
    poll_id: int,
    page: int = 1,
    page_size: int = 25,
    user: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        poll = get_poll(conn, poll_id)
        if poll is None or int(poll["tenant_id"]) != int(user["id"]):
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Poll not found")
        return get_poll_coverage_page(conn, poll_id=poll_id, page=page, page_size=page_size)


@router.patch("/api/v1/polls/{poll_id}")
async def update_poll_route(poll_id: int, payload: PollPayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_poll(conn, poll_id) is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Poll not found")
        update_poll(conn, poll_id=poll_id, **payload.model_dump())
        return serialize_poll(get_poll(conn, poll_id))


@router.get("/api/v1/texts/{text_id}/poll-pool")
async def get_text_poll_pool(text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        text_row = get_text(conn, text_id)
        if text_row is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Text not found")
        items = [serialize_poll(item) for item in list_queued_polls(conn, text_id=text_id)]
        policy = get_effective_poll_pool_policy(conn, text_id=text_id)
        queued_count = count_queued_polls(conn, text_id=text_id)
    return {
        "text_id": text_id,
        "queued_count": queued_count,
        "effective_threshold_percent": policy["threshold_percent"],
        "refill_when_below": policy["refill_when_below"],
        "target_size": policy["target_size"],
        "refill_batch_size": policy["refill_batch_size"],
        "next_poll": items[0] if items else None,
        "items": items,
    }


@router.post("/api/v1/texts/{text_id}/poll-pool/refill")
async def refill_text_poll_pool(text_id: int, user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    created = await fill_poll_pool(settings=runtime, database_url=settings.database_url, text_id=text_id)
    with db_session(settings.database_url) as conn:
        items = [serialize_poll(item) for item in list_queued_polls(conn, text_id=text_id)]
        policy = get_effective_poll_pool_policy(conn, text_id=text_id)
        queued_count = count_queued_polls(conn, text_id=text_id)
    return {
        "created": len(created),
        "text_id": text_id,
        "queued_count": queued_count,
        "effective_threshold_percent": policy["threshold_percent"],
        "refill_when_below": policy["refill_when_below"],
        "target_size": policy["target_size"],
        "refill_batch_size": policy["refill_batch_size"],
        "next_poll": items[0] if items else None,
        "items": items,
    }


@router.patch("/api/v1/polls/{poll_id}/pool-rank")
async def update_poll_pool_rank(poll_id: int, payload: PollRankPayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        poll = get_poll(conn, poll_id)
        if poll is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Poll not found")
        if str(poll["status"]) != "queued":
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="Only queued polls can be reordered")
        reordered = reorder_queued_poll(conn, poll_id=poll_id, pool_rank=payload.pool_rank)
    return serialize_poll(reordered)


@router.delete("/api/v1/polls/{poll_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_poll_route(poll_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_poll(conn, poll_id)
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
