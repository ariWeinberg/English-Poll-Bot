from __future__ import annotations

from datetime import timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services import generate_and_send_poll, send_pending_summaries


def build_scheduler(database_url: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    scheduler.add_job(
        run_due_jobs,
        CronTrigger(minute="*", timezone=timezone.utc),
        kwargs={"database_url": database_url},
        id="due_jobs",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


async def run_due_jobs(*, database_url: str) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.database import db_session, list_pending_texts
    from app.services import load_runtime_config

    sent = 0
    with db_session(database_url) as conn:
        texts = list_pending_texts(conn)
    for text in texts:
        runtime = load_runtime_config(database_url, int(text["tenant_id"]))
        if not runtime.scheduler_enabled or not runtime.greenapi_ready or not runtime.gemini_ready:
            continue
        now_local = datetime.now(ZoneInfo(runtime.timezone))
        minute_key = now_local.strftime("%H:%M")
        if minute_key in {text["morning_time"], text["evening_time"]}:
            await generate_and_send_poll(
                settings=runtime,
                database_url=database_url,
                text_id=int(text["id"]),
                scheduled_slot=minute_key,
            )
            sent += 1
        if minute_key in {text["summary_time_morning"], text["summary_time_evening"]}:
            await send_pending_summaries(settings=runtime, database_url=database_url, text_id=int(text["id"]))
    return sent
