from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import actions, auth, docs, learners, polls, schedule_rules, tenants, texts, votes
from app.config import settings
from app.core.logging import RequestLoggingRoute, configure_logging, get_logger
from app.database import init_db
from app.runtime import restart_scheduler
from app.scheduler import build_scheduler


logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings)
    logger.info("application.start")
    init_db(settings.database_url)
    scheduler = build_scheduler(settings.database_url)
    scheduler.start()
    logger.info("scheduler.started", extra={"job_count": len(scheduler.get_jobs())})
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
            logger.info("scheduler.stopped")
        logger.info("application.stop")


def create_app() -> FastAPI:
    configure_logging(settings)
    application = FastAPI(
        title="English WhatsApp Poll Bot API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.router.route_class = RequestLoggingRoute
    application.include_router(auth.router)
    application.include_router(docs.router)
    application.include_router(tenants.router)
    application.include_router(texts.router)
    application.include_router(schedule_rules.router)
    application.include_router(polls.router)
    application.include_router(votes.router)
    application.include_router(learners.router)
    application.include_router(actions.router)
    return application


app = create_app()


def restart_scheduler_for_tenant(tenant_id: int) -> None:
    del tenant_id
    restart_scheduler(app, build_scheduler=build_scheduler, database_url=settings.database_url)
