from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import actions, auth, chats, docs, learners, polls, schedule_rules, tenants, texts, votes, webhooks
from app.config import settings
from app.core.logging import RequestLoggingRoute, configure_logging, get_logger
from app.database import init_db


logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings)
    logger.info("application.start")
    logger.info(
        "application.scheduler_worker_required",
        extra={
            "scheduler_execution_owner": "app.scheduler_worker",
            "database_url": settings.database_url,
        },
    )
    init_db(settings.database_url)
    try:
        yield
    finally:
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
    application.include_router(chats.router)
    application.include_router(texts.router)
    application.include_router(schedule_rules.router)
    application.include_router(polls.router)
    application.include_router(votes.router)
    application.include_router(learners.router)
    application.include_router(webhooks.router)
    application.include_router(actions.router)
    return application


app = create_app()
