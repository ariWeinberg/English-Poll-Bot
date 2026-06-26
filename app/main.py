from __future__ import annotations

import base64
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.config import settings
from app.database import (
    all_poll_stats,
    create_poll,
    create_poll_vote,
    db_session,
    delete_poll,
    delete_poll_vote,
    delete_tenant,
    delete_text,
    export_stats_csv,
    get_poll,
    get_poll_vote_event,
    get_poll_vote,
    get_tenant,
    get_text,
    init_db,
    list_poll_votes_page,
    list_poll_vote_events_page,
    list_polls_page,
    list_tenants_page,
    list_texts_page,
    set_active_tenant,
    update_poll,
    update_poll_vote,
    upsert_tenant,
    upsert_text,
)
from app.scheduler import build_scheduler
from app.services import (
    generate_and_send_poll,
    generate_question,
    handle_greenapi_webhook,
    load_runtime_config,
    send_pending_summaries,
)


UPLOAD_DIR = Path("uploads")
security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.database_url)
    scheduler = build_scheduler(settings.database_url)
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(title="English WhatsApp Poll Bot API", lifespan=lifespan)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str


class TenantPayload(BaseModel):
    name: str = "Tenant"
    username: str = ""
    password: str = ""
    greenapi_api_url: str = "https://api.green-api.com"
    greenapi_id_instance: str = ""
    greenapi_api_token_instance: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    timezone: str = "Asia/Jerusalem"
    summary_enabled: bool = True
    scheduler_enabled: bool = True
    is_active: bool = True


class TextPayload(BaseModel):
    tenant_id: int
    title: str
    body: str
    chat_id: str
    morning_time: str = "08:30"
    evening_time: str = "18:00"
    summary_time_morning: str = "08:25"
    summary_time_evening: str = "17:55"
    enabled: bool = True


class PollPayload(BaseModel):
    tenant_id: int
    text_id: int
    question: str
    options: list[str] = Field(min_length=2)
    correct_option: str
    explanation: str = ""
    greenapi_message_id: str | None = None
    chat_id: str
    generated_from_text: str = ""
    status: str = "draft"
    scheduled_slot: str | None = None
    sent_at: str | None = None
    summary_sent_at: str | None = None


class PollVotePayload(BaseModel):
    poll_id: int
    option_name: str
    voter_wid: str


class PreviewRequest(BaseModel):
    text_id: int


class SendPollRequest(BaseModel):
    text_id: int
    scheduled_slot: str | None = "manual"


class SendSummaryRequest(BaseModel):
    text_id: int | None = None


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(data: str) -> str:
    digest = hmac.new(settings.jwt_secret.encode("utf-8"), data.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def create_token(tenant: dict[str, Any]) -> tuple[str, str]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_ttl_minutes)
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64encode(
        json.dumps(
            {
                "sub": str(tenant["id"]),
                "username": tenant["username"],
                "tenant_id": int(tenant["id"]),
                "exp": int(expires_at.timestamp()),
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{payload}"
    return f"{signing_input}.{_sign(signing_input)}", expires_at.isoformat()


def decode_token(token: str) -> dict[str, Any]:
    try:
        header, payload, signature = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    signing_input = f"{header}.{payload}"
    if not hmac.compare_digest(_sign(signing_input), signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    try:
        claims = json.loads(_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    if int(claims.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return claims


def current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict[str, Any]:
    claims = decode_token(credentials.credentials)
    with db_session(settings.database_url) as conn:
        tenant = get_tenant(conn, int(claims["tenant_id"]))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant not found")
    return dict(tenant)


def parse_bool(value: bool | None) -> bool | None:
    return value


def restart_scheduler_for_tenant(tenant_id: int) -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler and getattr(scheduler, "running", False):
        return
    if scheduler:
        scheduler.shutdown(wait=False)
    app.state.scheduler = build_scheduler(settings.database_url)
    app.state.scheduler.start()


def serialize_poll(row: dict[str, Any]) -> dict[str, Any]:
    poll = dict(row)
    try:
        poll["options"] = json.loads(poll.pop("options_json"))
    except (KeyError, TypeError, json.JSONDecodeError):
        poll["options"] = []
    return poll


@app.get("/api/v1/health")
async def health():
    return {"ok": True}


@app.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    with db_session(settings.database_url) as conn:
        tenant = conn.execute(
            "SELECT * FROM tenants WHERE username = %s AND password = %s LIMIT 1",
            (payload.username.strip(), payload.password.strip()),
        ).fetchone()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token, expires_at = create_token(dict(tenant))
    return TokenResponse(access_token=token, expires_at=expires_at)


@app.get("/api/v1/auth/me")
async def me(user: dict[str, Any] = Depends(current_user)):
    return user


@app.get("/api/v1/tenants")
async def tenants(
    page: int = 1,
    page_size: int = 25,
    is_active: bool | None = Query(None),
    search: str | None = None,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        return list_tenants_page(conn, page=page, page_size=page_size, is_active=parse_bool(is_active), search=search)


@app.post("/api/v1/tenants", status_code=201)
async def create_tenant(payload: TenantPayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        tenant_id = upsert_tenant(conn, tenant_id=None, **payload.model_dump())
        if payload.is_active:
            set_active_tenant(conn, tenant_id)
        tenant = get_tenant(conn, tenant_id)
    restart_scheduler_for_tenant(tenant_id)
    return tenant


@app.get("/api/v1/tenants/{tenant_id}")
async def tenant(tenant_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_tenant(conn, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return row


@app.patch("/api/v1/tenants/{tenant_id}")
async def update_tenant_route(tenant_id: int, payload: TenantPayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_tenant(conn, tenant_id) is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        saved_id = upsert_tenant(conn, tenant_id=tenant_id, **payload.model_dump())
        if payload.is_active:
            set_active_tenant(conn, saved_id)
        row = get_tenant(conn, saved_id)
    restart_scheduler_for_tenant(saved_id)
    return row


@app.delete("/api/v1/tenants/{tenant_id}", status_code=204)
async def delete_tenant_route(tenant_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_tenant(conn, tenant_id)
    return Response(status_code=204)


@app.post("/api/v1/tenants/{tenant_id}/activate")
async def activate_tenant(tenant_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_tenant(conn, tenant_id) is None:
            raise HTTPException(status_code=404, detail="Tenant not found")
        set_active_tenant(conn, tenant_id)
        row = get_tenant(conn, tenant_id)
    restart_scheduler_for_tenant(tenant_id)
    token, expires_at = create_token(dict(row))
    return {"tenant": row, "access_token": token, "token_type": "bearer", "expires_at": expires_at}


@app.get("/api/v1/texts")
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


@app.post("/api/v1/texts", status_code=201)
async def create_text(
    tenant_id: int = Form(...),
    title: str = Form(...),
    body: str = Form(...),
    chat_id: str = Form(...),
    morning_time: str = Form("08:30"),
    evening_time: str = Form("18:00"),
    summary_time_morning: str = Form("08:25"),
    summary_time_evening: str = Form("17:55"),
    enabled: bool = Form(True),
    attachment: UploadFile | None = File(None),
    _: dict[str, Any] = Depends(current_user),
):
    attachment_name, attachment_path = await save_attachment(attachment)
    with db_session(settings.database_url) as conn:
        text_id = upsert_text(
            conn,
            text_id=None,
            tenant_id=tenant_id,
            title=title,
            body=body,
            chat_id=chat_id,
            morning_time=morning_time,
            evening_time=evening_time,
            summary_time_morning=summary_time_morning,
            summary_time_evening=summary_time_evening,
            enabled=enabled,
            attachment_name=attachment_name,
            attachment_path=attachment_path,
        )
        return get_text(conn, text_id)


@app.get("/api/v1/texts/{text_id}")
async def text(text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_text(conn, text_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Text not found")
    return row


@app.patch("/api/v1/texts/{text_id}")
async def update_text_route(payload: TextPayload, text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_text(conn, text_id) is None:
            raise HTTPException(status_code=404, detail="Text not found")
        upsert_text(conn, text_id=text_id, attachment_name=None, attachment_path=None, **payload.model_dump())
        return get_text(conn, text_id)


@app.delete("/api/v1/texts/{text_id}", status_code=204)
async def delete_text_route(text_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_text(conn, text_id)
    return Response(status_code=204)


async def save_attachment(attachment: UploadFile | None) -> tuple[str | None, str | None]:
    if not attachment or not attachment.filename:
        return None, None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(attachment.filename).suffix
    stored_name = f"{uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(await attachment.read())
    return attachment.filename, str(stored_path)


@app.get("/api/v1/polls")
async def polls(
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    text_id: int | None = None,
    status: str | None = None,
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
            scheduled_slot=scheduled_slot,
            sent_from=sent_from,
            sent_to=sent_to,
        )
    result["items"] = [serialize_poll(item) for item in result["items"]]
    return result


@app.post("/api/v1/polls", status_code=201)
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
        )
        update_poll(conn, poll_id=poll_id, **payload.model_dump())
        return serialize_poll(get_poll(conn, poll_id))


@app.get("/api/v1/polls/stats")
async def poll_stats_route(
    tenant_id: int | None = None,
    limit: int = 25,
    user: dict[str, Any] = Depends(current_user),
):
    scoped_tenant = tenant_id if tenant_id is not None else int(user["id"])
    with db_session(settings.database_url) as conn:
        return all_poll_stats(conn, limit=limit, tenant_id=scoped_tenant)


@app.get("/api/v1/polls/export.csv")
async def export_csv(tenant_id: int | None = None, user: dict[str, Any] = Depends(current_user)):
    scoped_tenant = tenant_id if tenant_id is not None else int(user["id"])
    with db_session(settings.database_url) as conn:
        csv_text = export_stats_csv(conn, tenant_id=scoped_tenant)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=poll-stats.csv"},
    )


@app.get("/api/v1/polls/{poll_id}")
async def poll(poll_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_poll(conn, poll_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Poll not found")
    return serialize_poll(row)


@app.patch("/api/v1/polls/{poll_id}")
async def update_poll_route(poll_id: int, payload: PollPayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_poll(conn, poll_id) is None:
            raise HTTPException(status_code=404, detail="Poll not found")
        update_poll(conn, poll_id=poll_id, **payload.model_dump())
        return serialize_poll(get_poll(conn, poll_id))


@app.delete("/api/v1/polls/{poll_id}", status_code=204)
async def delete_poll_route(poll_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_poll(conn, poll_id)
    return Response(status_code=204)


@app.get("/api/v1/poll-votes")
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


@app.get("/api/v1/poll-vote-events")
async def poll_vote_events(
    page: int = 1,
    page_size: int = 25,
    poll_id: int | None = None,
    option_name: str | None = None,
    voter_wid: str | None = None,
    _: dict[str, Any] = Depends(current_user),
):
    with db_session(settings.database_url) as conn:
        return list_poll_vote_events_page(
            conn,
            page=page,
            page_size=page_size,
            poll_id=poll_id,
            option_name=option_name,
            voter_wid=voter_wid,
        )


@app.post("/api/v1/poll-votes", status_code=201)
async def create_vote(payload: PollVotePayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        vote_id = create_poll_vote(conn, **payload.model_dump())
        return get_poll_vote(conn, vote_id)


@app.get("/api/v1/poll-votes/{vote_id}")
async def poll_vote(vote_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_poll_vote(conn, vote_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Poll vote not found")
    return row


@app.get("/api/v1/poll-vote-events/{event_id}")
async def poll_vote_event(event_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        row = get_poll_vote_event(conn, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Poll vote event not found")
    return row


@app.patch("/api/v1/poll-votes/{vote_id}")
async def update_vote(vote_id: int, payload: PollVotePayload, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        if get_poll_vote(conn, vote_id) is None:
            raise HTTPException(status_code=404, detail="Poll vote not found")
        update_poll_vote(conn, vote_id=vote_id, **payload.model_dump())
        return get_poll_vote(conn, vote_id)


@app.delete("/api/v1/poll-votes/{vote_id}", status_code=204)
async def delete_vote(vote_id: int, _: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        delete_poll_vote(conn, vote_id)
    return Response(status_code=204)


@app.post("/api/v1/questions/preview")
async def preview_question(payload: PreviewRequest, user: dict[str, Any] = Depends(current_user)):
    with db_session(settings.database_url) as conn:
        text_row = get_text(conn, payload.text_id)
    if text_row is None:
        raise HTTPException(status_code=404, detail="Text not found")
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    return await generate_question(runtime, text_row["body"])


@app.post("/api/v1/polls/send-now")
async def send_now(payload: SendPollRequest, user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    poll_id = await generate_and_send_poll(
        settings=runtime,
        database_url=settings.database_url,
        text_id=payload.text_id,
        scheduled_slot=payload.scheduled_slot,
    )
    return {"poll_id": poll_id}


@app.post("/api/v1/summaries/send-now")
async def summary_now(payload: SendSummaryRequest, user: dict[str, Any] = Depends(current_user)):
    runtime = load_runtime_config(settings.database_url, int(user["id"]))
    count = await send_pending_summaries(settings=runtime, database_url=settings.database_url, text_id=payload.text_id)
    return {"sent": count}


@app.post("/webhooks/greenapi/{tenant_id}")
async def greenapi_webhook(tenant_id: int, payload: dict[str, Any]):
    handled = handle_greenapi_webhook(database_url=settings.database_url, payload=payload, tenant_id=tenant_id)
    return {"ok": True, "handled": handled}
