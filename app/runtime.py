from __future__ import annotations

from fastapi import FastAPI


def restart_scheduler(app: FastAPI, *, build_scheduler, database_url: str) -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler and getattr(scheduler, "running", False):
        return
    if scheduler:
        scheduler.shutdown(wait=False)
    app.state.scheduler = build_scheduler(database_url)
    app.state.scheduler.start()


def restart_default_scheduler(*, build_scheduler, database_url: str) -> None:
    from app.main import app

    restart_scheduler(app, build_scheduler=build_scheduler, database_url=database_url)
