from pathlib import Path

from app.database import db_session, init_db, upsert_text, upsert_tenant
from app.scheduler import build_scheduler


def test_scheduler_registers_minute_tick(tmp_path: Path):
    db_path = tmp_path / "bot.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        tenant_id = upsert_tenant(
            conn,
            tenant_id=1,
            name="Tenant A",
            greenapi_api_url="https://api.green-api.com",
            greenapi_id_instance="7103000000",
            greenapi_api_token_instance="abc123",
            gemini_api_key="gemini-key",
            gemini_model="gemini-3.5-flash",
            timezone="Asia/Jerusalem",
            summary_enabled=True,
            scheduler_enabled=True,
            is_active=True,
        )
        upsert_text(
            conn,
            text_id=None,
            tenant_id=tenant_id,
            title="Text A",
            body="Body",
            chat_id="group@g.us",
            morning_time="08:30",
            evening_time="18:00",
            summary_time_morning="08:25",
            summary_time_evening="17:55",
            enabled=True,
        )

    scheduler = build_scheduler(db_path)
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert "due_jobs" in jobs
    assert jobs["due_jobs"].kwargs["db_path"] == db_path
