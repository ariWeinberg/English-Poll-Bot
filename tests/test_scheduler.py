import os

import pytest

from app.database import db_session, init_db, upsert_text, upsert_tenant
from app.scheduler import build_scheduler
from app.main import app, restart_scheduler_for_tenant


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
    init_db(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_scheduler_registers_minute_tick():
    database_url = reset_db()
    with db_session(database_url) as conn:
        tenant_id = upsert_tenant(
            conn,
            tenant_id=1,
            name="Tenant A",
            username="tenant-a",
            password="secret",
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

    scheduler = build_scheduler(database_url)
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert "due_jobs" in jobs
    assert jobs["due_jobs"].kwargs["database_url"] == database_url


def test_restart_scheduler_keeps_existing_running_scheduler(monkeypatch):
    class DummyScheduler:
        def __init__(self):
            self.running = True
            self.shutdown_called = False

        def shutdown(self, wait=False):
            self.shutdown_called = True

    dummy = DummyScheduler()
    app.state.scheduler = dummy

    def fail_build_scheduler(_database_url: str):
        raise AssertionError("build_scheduler should not be called for a running scheduler")

    monkeypatch.setattr("app.main.build_scheduler", fail_build_scheduler)

    restart_scheduler_for_tenant(1)

    assert app.state.scheduler is dummy
    assert dummy.shutdown_called is False
