from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import (
    all_poll_stats,
    db_session,
    delete_text,
    delete_tenant,
    export_stats_csv,
    get_active_tenant,
    get_source_text,
    get_tenant,
    get_text,
    init_db,
    list_tenants,
    list_texts,
    set_active_tenant,
    set_source_text,
    upsert_text,
    upsert_tenant,
)
from app.scheduler import build_scheduler
from app.services import (
    generate_and_send_poll,
    generate_question,
    handle_greenapi_webhook,
    load_runtime_config,
    send_pending_summaries,
)


templates = Jinja2Templates(directory="app/templates")
UPLOAD_DIR = Path("uploads")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.database_path)
    scheduler = None
    runtime = load_runtime_config(settings.database_path)
    if runtime.scheduler_enabled and runtime.greenapi_ready and runtime.gemini_ready:
        scheduler = build_scheduler(settings.database_path)
        scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(title="English WhatsApp Poll Bot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def redirect_home(message: str | None = None, error: str | None = None, tenant_id: int | None = None) -> RedirectResponse:
    parts = []
    if tenant_id is not None:
        parts.append(f"tenant_id={tenant_id}")
    if message:
        parts.append(f"message={message}")
    if error:
        parts.append(f"error={error}")
    suffix = f"?{'&'.join(parts)}" if parts else ""
    return RedirectResponse(f"/{suffix}", status_code=303)


def is_configured(config: dict[str, str]) -> bool:
    return all(
        (
            bool(config.get("greenapi_api_url", "").strip()),
            bool(config.get("greenapi_id_instance", "").strip()),
            bool(config.get("greenapi_api_token_instance", "").strip()),
            bool(config.get("gemini_api_key", "").strip()),
        )
    )


def resolve_tenant_id(request: Request) -> int | None:
    tenant_id = request.query_params.get("tenant_id")
    return int(tenant_id) if tenant_id and tenant_id.isdigit() else None


def render_index(request: Request, *, message: str | None = None, error: str | None = None):
    tenant_id = resolve_tenant_id(request)
    with db_session(settings.database_path) as conn:
        tenants = list_tenants(conn)
        tenant = get_tenant(conn, tenant_id) if tenant_id else get_active_tenant(conn)
        texts = list_texts(conn, int(tenant["id"]))
        polls = all_poll_stats(conn, tenant_id=int(tenant["id"]))
        config = dict(tenant)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "tenants": tenants,
            "tenant": tenant,
            "texts": texts,
            "poll_stats": polls,
            "config": config,
            "message": message,
            "error": error,
            "configured": is_configured(config),
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, message: str | None = None, error: str | None = None):
    return render_index(request, message=message, error=error)


@app.post("/tenants/save")
async def save_tenant(
    request: Request,
    tenant_id: int | None = Form(None),
    name: str = Form(...),
    greenapi_api_url: str = Form(...),
    greenapi_id_instance: str = Form(...),
    greenapi_api_token_instance: str = Form(...),
    gemini_api_key: str = Form(...),
    gemini_model: str = Form("gemini-3.5-flash"),
    timezone: str = Form("Asia/Jerusalem"),
    summary_enabled: str = Form("false"),
    scheduler_enabled: str = Form("false"),
    is_active: str = Form("true"),
):
    with db_session(settings.database_path) as conn:
        saved_id = upsert_tenant(
            conn,
            tenant_id=tenant_id,
            name=name,
            greenapi_api_url=greenapi_api_url,
            greenapi_id_instance=greenapi_id_instance,
            greenapi_api_token_instance=greenapi_api_token_instance,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            timezone=timezone,
            summary_enabled=summary_enabled == "true",
            scheduler_enabled=scheduler_enabled == "true",
            is_active=is_active == "true",
        )
        if is_active == "true":
            set_active_tenant(conn, saved_id)

    scheduler = getattr(app.state, "scheduler", None)
    runtime = load_runtime_config(settings.database_path, saved_id)
    if scheduler:
        scheduler.shutdown(wait=False)
    if runtime.scheduler_enabled and runtime.greenapi_ready and runtime.gemini_ready:
        new_scheduler = build_scheduler(settings.database_path)
        new_scheduler.start()
        app.state.scheduler = new_scheduler
    else:
        app.state.scheduler = None
    return redirect_home(message="Tenant saved", tenant_id=saved_id)


@app.post("/tenants/{tenant_id}/activate")
async def activate_tenant(tenant_id: int):
    with db_session(settings.database_path) as conn:
        set_active_tenant(conn, tenant_id)
    return redirect_home(message="Tenant activated", tenant_id=tenant_id)


@app.post("/texts/save")
async def save_text(
    tenant_id: int = Form(...),
    text_id: int | None = Form(None),
    title: str = Form(...),
    body: str = Form(...),
    chat_id: str = Form(...),
    morning_time: str = Form("08:30"),
    evening_time: str = Form("18:00"),
    summary_time_morning: str = Form("08:25"),
    summary_time_evening: str = Form("17:55"),
    enabled: str = Form("true"),
    attachment: UploadFile | None = File(None),
):
    attachment_name = None
    attachment_path = None
    if attachment and attachment.filename:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(attachment.filename).suffix
        stored_name = f"{uuid4().hex}{suffix}"
        stored_path = UPLOAD_DIR / stored_name
        stored_path.write_bytes(await attachment.read())
        attachment_name = attachment.filename
        attachment_path = str(stored_path)
    with db_session(settings.database_path) as conn:
        saved_id = upsert_text(
            conn,
            text_id=text_id,
            tenant_id=tenant_id,
            title=title,
            body=body,
            chat_id=chat_id,
            morning_time=morning_time,
            evening_time=evening_time,
            summary_time_morning=summary_time_morning,
            summary_time_evening=summary_time_evening,
            enabled=enabled == "true",
            attachment_name=attachment_name,
            attachment_path=attachment_path,
        )
    return redirect_home(message="Text saved", tenant_id=tenant_id)


@app.post("/texts/{text_id}/delete")
async def remove_text(text_id: int):
    with db_session(settings.database_path) as conn:
        text = get_text(conn, text_id)
        tenant_id = int(text["tenant_id"]) if text else None
        delete_text(conn, text_id)
    return redirect_home(message="Text deleted", tenant_id=tenant_id)


@app.post("/tenants/{tenant_id}/delete")
async def remove_tenant(tenant_id: int):
    with db_session(settings.database_path) as conn:
        delete_tenant(conn, tenant_id)
    return redirect_home(message="Tenant deleted")


@app.post("/preview", response_class=HTMLResponse)
async def preview_question(request: Request, text_id: int = Form(...)):
    tenant_id = resolve_tenant_id(request)
    with db_session(settings.database_path) as conn:
        text = get_text(conn, text_id)
        if text is None:
            return render_index(request, error="Text not found")
        tenant = get_tenant(conn, int(text["tenant_id"])) if tenant_id is None else get_tenant(conn, tenant_id)
        config = dict(tenant)
        polls = all_poll_stats(conn, tenant_id=int(text["tenant_id"]))
        tenants = list_tenants(conn)
        texts = list_texts(conn, int(text["tenant_id"]))
    runtime = load_runtime_config(settings.database_path, int(text["tenant_id"]))
    try:
        question = await generate_question(runtime, text["body"])
    except Exception as exc:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "tenants": tenants,
                "tenant": tenant,
                "texts": texts,
                "poll_stats": polls,
                "config": config,
                "message": None,
                "error": str(exc),
                "configured": is_configured(config),
            },
            status_code=400,
        )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "tenants": tenants,
            "tenant": tenant,
            "texts": texts,
            "poll_stats": polls,
            "config": config,
            "message": "Preview generated",
            "error": None,
            "configured": is_configured(config),
            "preview": question,
            "preview_text_id": text_id,
        },
    )


@app.post("/polls/send-now")
async def send_now(text_id: int = Form(...)):
    try:
        with db_session(settings.database_path) as conn:
            text = get_text(conn, text_id)
            if text is None:
                raise ValueError("Text not found.")
        runtime = load_runtime_config(settings.database_path, int(text["tenant_id"]))
        await generate_and_send_poll(
            settings=runtime,
            db_path=settings.database_path,
            text_id=text_id,
            scheduled_slot="manual",
        )
    except Exception as exc:
        return redirect_home(error=str(exc), tenant_id=int(text["tenant_id"]) if "text" in locals() and text else None)
    return redirect_home(message="Poll sent", tenant_id=int(text["tenant_id"]))


@app.post("/summaries/send-now")
async def summary_now(text_id: int = Form(...)):
    try:
        with db_session(settings.database_path) as conn:
            text = get_text(conn, text_id)
            if text is None:
                raise ValueError("Text not found.")
        runtime = load_runtime_config(settings.database_path, int(text["tenant_id"]))
        count = await send_pending_summaries(settings=runtime, db_path=settings.database_path, text_id=text_id)
    except Exception as exc:
        return redirect_home(error=str(exc), tenant_id=int(text["tenant_id"]) if "text" in locals() and text else None)
    return redirect_home(message=f"Sent {count} summaries", tenant_id=int(text["tenant_id"]))


@app.post("/webhooks/greenapi")
async def greenapi_webhook(payload: dict):
    handled = handle_greenapi_webhook(db_path=settings.database_path, payload=payload)
    return {"ok": True, "handled": handled}


@app.get("/export.csv")
async def export_csv(tenant_id: int | None = None):
    with db_session(settings.database_path) as conn:
        csv_text = export_stats_csv(conn, tenant_id=tenant_id)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=poll-stats.csv"},
    )
