import os
from datetime import datetime

import pytest

from app.database import db_session, init_db, list_text_schedule_rules, upsert_text, upsert_tenant
from app.scheduler import build_scheduler, run_due_jobs
from app.main import app, restart_scheduler_for_tenant


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE tenant_group_chats, text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
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
            enabled=True,
            new_rules=[
                {
                    "delivery_type": "poll",
                    "rule_type": "daily_time",
                    "time": "08:30",
                    "count_mode": "fixed",
                    "count_value": 1,
                }
            ],
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


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.asyncio
async def test_run_due_jobs_uses_rule_labels_and_counts(monkeypatch):
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
        text_id = upsert_text(
            conn,
            text_id=None,
            tenant_id=tenant_id,
            title="Text A",
            body="Body",
            chat_id="group@g.us",
            enabled=True,
            new_rules=[
                {
                    "delivery_type": "poll",
                    "rule_type": "daily_time",
                    "time": "08:30",
                    "count_mode": "fixed",
                    "count_value": 2,
                },
                {
                    "delivery_type": "summary",
                    "rule_type": "weekday_time",
                    "time": "08:30",
                    "weekdays": [0],
                    "count_mode": "fixed",
                    "count_value": 1,
                },
            ],
        )
        poll_rule = next(
            rule for rule in list_text_schedule_rules(conn, text_id=text_id) if rule["delivery_type"] == "poll"
        )

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 29, 8, 30, tzinfo=tz)

    sent_slots: list[str | None] = []

    async def fake_send_poll(*, scheduled_slot=None, **kwargs):
        sent_slots.append(scheduled_slot)
        return 1

    async def fake_send_summary(**kwargs):
        return 1

    monkeypatch.setattr("app.scheduler.datetime", FrozenDateTime)
    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)
    monkeypatch.setattr("app.scheduler.send_pending_summaries", fake_send_summary)

    sent = await run_due_jobs(database_url=database_url)

    assert sent == 2
    assert sent_slots == [f"rule:{poll_rule['id']}:poll:08:30", f"rule:{poll_rule['id']}:poll:08:30"]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.asyncio
async def test_random_window_rules_plan_once_per_day(monkeypatch):
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
        text_id = upsert_text(
            conn,
            text_id=None,
            tenant_id=tenant_id,
            title="Text A",
            body="Body",
            chat_id="group@g.us",
            enabled=True,
            new_rules=[
                {
                    "delivery_type": "poll",
                    "rule_type": "random_window",
                    "window_start": "09:00",
                    "window_end": "09:05",
                    "count_mode": "fixed",
                    "count_value": 2,
                }
            ],
        )

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 29, 9, 1, tzinfo=tz)

    calls: list[str | None] = []

    async def fake_send_poll(*, scheduled_slot=None, **kwargs):
        calls.append(scheduled_slot)
        return 1

    monkeypatch.setattr("app.scheduler.datetime", FrozenDateTime)
    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)
    monkeypatch.setattr("app.scheduler.random.randint", lambda start, end: 1)

    await run_due_jobs(database_url=database_url)
    await run_due_jobs(database_url=database_url)

    with db_session(database_url) as conn:
        plans = conn.execute("SELECT * FROM text_schedule_rule_random_plans WHERE text_id = %s", (text_id,)).fetchall()

    assert len(calls) == 2
    assert len(plans) == 1
