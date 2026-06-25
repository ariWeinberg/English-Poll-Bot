from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import (
    all_poll_stats,
    db_session,
    delete_text,
    delete_tenant,
    export_stats_csv,
    get_active_tenant,
    get_tenant,
    get_text,
    init_db,
    list_tenants,
    list_texts,
    set_active_tenant,
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
    init_db(settings.database_url)
    scheduler = None
    runtime = load_runtime_config(settings.database_url)
    if runtime.scheduler_enabled and runtime.greenapi_ready and runtime.gemini_ready:
        scheduler = build_scheduler(settings.database_url)
        scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(title="English WhatsApp Poll Bot", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def redirect(url: str, *, message: str | None = None, error: str | None = None) -> RedirectResponse:
    parts: list[str] = []
    if message:
        parts.append(f"message={message}")
    if error:
        parts.append(f"error={error}")
    if parts:
        url = f"{url}?{'&'.join(parts)}"
    return RedirectResponse(url, status_code=303)


def get_session_tenant_id(request: Request) -> int | None:
    value = request.session.get("tenant_id")
    return int(value) if isinstance(value, int | str) and str(value).isdigit() else None


def require_login(request: Request) -> int | RedirectResponse:
    tenant_id = get_session_tenant_id(request)
    if tenant_id is None:
        return redirect("/login")
    return tenant_id


def render(request: Request, template: str, context: dict, status_code: int = 200):
    return templates.TemplateResponse(request=request, name=template, context=context, status_code=status_code)


def is_configured(tenant: dict[str, str]) -> bool:
    return all(
        (
            bool(tenant.get("greenapi_api_url", "").strip()),
            bool(tenant.get("greenapi_id_instance", "").strip()),
            bool(tenant.get("greenapi_api_token_instance", "").strip()),
            bool(tenant.get("gemini_api_key", "").strip()),
        )
    )


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    tenant_id = get_session_tenant_id(request)
    if tenant_id is not None:
        return redirect("/dashboard")
    return render(request, "landing.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, error: str | None = None):
    with db_session(settings.database_url) as conn:
        tenants = list_tenants(conn)
    return render(request, "login.html", {"request": request, "tenants": tenants, "error": error})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with db_session(settings.database_url) as conn:
        tenant = conn.execute(
            "SELECT * FROM tenants WHERE username = %s AND password = %s LIMIT 1",
            (username.strip(), password.strip()),
        ).fetchone()
    if tenant is None:
        return redirect("/login", error="Invalid username or password")
    request.session["tenant_id"] = int(tenant["id"])
    return redirect("/dashboard")


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return redirect("/")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, message: str | None = None, error: str | None = None):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    tenant_id = int(login_gate)
    with db_session(settings.database_url) as conn:
        tenant = get_tenant(conn, tenant_id)
        tenants = list_tenants(conn)
        texts = list_texts(conn, tenant_id)
        polls = all_poll_stats(conn, tenant_id=tenant_id)
    return render(
        request,
        "dashboard.html",
        {
            "request": request,
            "tenant": tenant,
            "tenants": tenants,
            "texts": texts,
            "poll_stats": polls,
            "configured": is_configured(dict(tenant)),
            "message": message,
            "error": error,
        },
    )


@app.post("/tenants/save")
async def save_tenant(
    request: Request,
    tenant_id: int | None = Form(None),
    name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
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
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    with db_session(settings.database_url) as conn:
        saved_id = upsert_tenant(
            conn,
            tenant_id=tenant_id,
            name=name,
            username=username,
            password=password,
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
    runtime = load_runtime_config(settings.database_url, saved_id)
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)
    if runtime.scheduler_enabled and runtime.greenapi_ready and runtime.gemini_ready:
        app.state.scheduler = build_scheduler(settings.database_url)
        app.state.scheduler.start()
    else:
        app.state.scheduler = None
    request.session["tenant_id"] = saved_id
    return redirect("/dashboard", message="Tenant saved")


@app.post("/tenants/{tenant_id}/activate")
async def activate_tenant(request: Request, tenant_id: int):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    with db_session(settings.database_url) as conn:
        set_active_tenant(conn, tenant_id)
    request.session["tenant_id"] = tenant_id
    return redirect("/dashboard", message="Tenant activated")


@app.get("/texts", response_class=HTMLResponse)
async def texts_page(request: Request, message: str | None = None, error: str | None = None):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    tenant_id = int(login_gate)
    with db_session(settings.database_url) as conn:
        tenant = get_tenant(conn, tenant_id)
        texts = list_texts(conn, tenant_id)
    return render(
        request,
        "texts.html",
        {
            "request": request,
            "tenant": tenant,
            "texts": texts,
            "message": message,
            "error": error,
        },
    )


@app.post("/texts/save")
async def save_text(
    request: Request,
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
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
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
    with db_session(settings.database_url) as conn:
        upsert_text(
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
    return redirect("/texts", message="Text saved")


@app.post("/texts/{text_id}/delete")
async def remove_text(request: Request, text_id: int):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    with db_session(settings.database_url) as conn:
        delete_text(conn, text_id)
    return redirect("/texts", message="Text deleted")


@app.post("/preview")
async def preview_question(request: Request, text_id: int = Form(...)):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    tenant_id = int(login_gate)
    with db_session(settings.database_url) as conn:
        text = get_text(conn, text_id)
        if text is None:
            return redirect("/texts", error="Text not found")
    runtime = load_runtime_config(settings.database_url, tenant_id)
    question = await generate_question(runtime, text["body"])
    with db_session(settings.database_url) as conn:
        tenant = get_tenant(conn, tenant_id)
        texts = list_texts(conn, tenant_id)
        polls = all_poll_stats(conn, tenant_id=tenant_id)
        tenants = list_tenants(conn)
    return render(request, "dashboard.html", {
        "request": request,
        "tenant": tenant,
        "tenants": tenants,
        "texts": texts,
        "poll_stats": polls,
        "configured": is_configured(dict(tenant)),
        "preview": question,
    })


@app.post("/polls/send-now")
async def send_now(request: Request, text_id: int = Form(...)):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    tenant_id = int(login_gate)
    try:
        runtime = load_runtime_config(settings.database_url, tenant_id)
        await generate_and_send_poll(
            settings=runtime,
            database_url=settings.database_url,
            text_id=text_id,
            scheduled_slot="manual",
        )
    except Exception as exc:
        return redirect("/texts", error=str(exc))
    return redirect("/texts", message="Poll sent")


@app.post("/summaries/send-now")
async def summary_now(request: Request, text_id: int = Form(...)):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    tenant_id = int(login_gate)
    try:
        runtime = load_runtime_config(settings.database_url, tenant_id)
        count = await send_pending_summaries(settings=runtime, database_url=settings.database_url, text_id=text_id)
    except Exception as exc:
        return redirect("/texts", error=str(exc))
    return redirect("/texts", message=f"Sent {count} summaries")


@app.post("/webhooks/greenapi")
async def greenapi_webhook(payload: dict):
    handled = handle_greenapi_webhook(database_url=settings.database_url, payload=payload)
    return {"ok": True, "handled": handled}


@app.get("/export.csv")
async def export_csv(request: Request, tenant_id: int | None = None):
    login_gate = require_login(request)
    if isinstance(login_gate, RedirectResponse):
        return login_gate
    tenant_id = int(login_gate)
    with db_session(settings.database_url) as conn:
        csv_text = export_stats_csv(conn, tenant_id=tenant_id)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=poll-stats.csv"},
    )
