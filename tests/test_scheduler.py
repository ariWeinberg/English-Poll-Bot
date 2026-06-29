import os
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.logging import configure_logging
from app.database import db_session, get_app_config_json, init_db, list_text_schedule_rules, upsert_text, upsert_tenant
from app.scheduler import SCHEDULER_STATUS_KEY, build_scheduler, run_due_jobs


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE app_config, scheduled_send_attempts, tenant_group_chats, text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
    init_db(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_scheduler_registers_minute_tick():
    database_url = reset_db()
    scheduler = build_scheduler(database_url)
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert "due_jobs" in jobs
    assert jobs["due_jobs"].kwargs["database_url"] == database_url
    assert jobs["due_jobs"].kwargs["debug_enabled"] is False


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.anyio
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

    sent_slots: list[str | None] = []

    async def fake_send_poll(*, scheduled_slot=None, **kwargs):
        sent_slots.append(scheduled_slot)
        return 101

    async def fake_send_summary(**kwargs):
        return 1

    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)
    monkeypatch.setattr("app.scheduler.send_pending_summaries", fake_send_summary)

    sent = await run_due_jobs(database_url=database_url, now_utc=datetime(2026, 6, 29, 5, 30, tzinfo=timezone.utc))

    assert sent == 2
    assert sent_slots == [f"rule:{poll_rule['id']}:poll:08:30", f"rule:{poll_rule['id']}:poll:08:30"]
    with db_session(database_url) as conn:
        attempts = conn.execute("SELECT status, scheduled_slot FROM scheduled_send_attempts ORDER BY id ASC").fetchall()
    assert [row["status"] for row in attempts] == ["sent", "sent", "sent"]
    assert [row["scheduled_slot"] for row in attempts[:2]] == [sent_slots[0], sent_slots[1]]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.anyio
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

    calls: list[str | None] = []

    async def fake_send_poll(*, scheduled_slot=None, **kwargs):
        calls.append(scheduled_slot)
        return 1

    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)
    monkeypatch.setattr("app.scheduler.random.randint", lambda start, end: 1)

    now_utc = datetime(2026, 6, 29, 6, 1, tzinfo=timezone.utc)
    await run_due_jobs(database_url=database_url, now_utc=now_utc)
    await run_due_jobs(database_url=database_url, now_utc=now_utc)

    with db_session(database_url) as conn:
        plans = conn.execute("SELECT * FROM text_schedule_rule_random_plans WHERE text_id = %s", (text_id,)).fetchall()
        attempts = conn.execute("SELECT * FROM scheduled_send_attempts WHERE text_id = %s", (text_id,)).fetchall()

    assert len(calls) == 2
    assert len(plans) == 1
    assert len(attempts) == 2


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.anyio
async def test_run_due_jobs_continues_after_text_timezone_failure(monkeypatch):
    database_url = reset_db()
    with db_session(database_url) as conn:
        broken_tenant_id = upsert_tenant(
            conn,
            tenant_id=1,
            name="Broken Tenant",
            username="broken-tenant",
            password="secret",
            greenapi_api_url="https://api.green-api.com",
            greenapi_id_instance="7103000000",
            greenapi_api_token_instance="abc123",
            gemini_api_key="gemini-key",
            gemini_model="gemini-3.5-flash",
            timezone="Bad/Timezone",
            summary_enabled=True,
            scheduler_enabled=True,
            is_active=True,
        )
        upsert_text(
            conn,
            text_id=None,
            tenant_id=broken_tenant_id,
            title="Broken Text",
            body="Body",
            chat_id="broken@g.us",
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
        working_tenant_id = upsert_tenant(
            conn,
            tenant_id=2,
            name="Working Tenant",
            username="working-tenant",
            password="secret",
            greenapi_api_url="https://api.green-api.com",
            greenapi_id_instance="7103000001",
            greenapi_api_token_instance="abc124",
            gemini_api_key="gemini-key",
            gemini_model="gemini-3.5-flash",
            timezone="UTC",
            summary_enabled=True,
            scheduler_enabled=True,
            is_active=True,
        )
        working_text_id = upsert_text(
            conn,
            text_id=None,
            tenant_id=working_tenant_id,
            title="Working Text",
            body="Body",
            chat_id="working@g.us",
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

    sent_text_ids: list[int] = []

    async def fake_send_poll(*, text_id=None, **kwargs):
        sent_text_ids.append(text_id)
        return 1

    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)

    sent = await run_due_jobs(database_url=database_url, now_utc=datetime(2026, 6, 29, 8, 30, tzinfo=timezone.utc))

    assert sent == 1
    assert sent_text_ids == [working_text_id]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.anyio
async def test_run_due_jobs_keeps_local_time_across_dst(monkeypatch):
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
                    "time": "19:00",
                    "count_mode": "fixed",
                    "count_value": 1,
                }
            ],
        )

    tick_times = [
        datetime(2026, 6, 29, 16, 0, tzinfo=timezone.utc),
        datetime(2026, 12, 29, 17, 0, tzinfo=timezone.utc),
    ]
    seen_slots: list[str | None] = []

    async def fake_send_poll(*, scheduled_slot=None, **kwargs):
        seen_slots.append(scheduled_slot)
        return 7

    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)

    for tick_time in tick_times:
        await run_due_jobs(database_url=database_url, now_utc=tick_time)

    assert seen_slots == ["rule:1:poll:19:00", "rule:1:poll:19:00"]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.anyio
async def test_run_due_jobs_records_failed_attempt_and_heartbeat(monkeypatch):
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
            timezone="UTC",
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

    async def fake_send_poll(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)

    await run_due_jobs(database_url=database_url, now_utc=datetime(2026, 6, 29, 8, 30, tzinfo=timezone.utc))

    with db_session(database_url) as conn:
        attempts = conn.execute("SELECT status, error FROM scheduled_send_attempts ORDER BY id ASC").fetchall()
        status = get_app_config_json(conn, key=SCHEDULER_STATUS_KEY)

    assert len(attempts) == 1
    assert attempts[0]["status"] == "failed"
    assert "provider down" in str(attempts[0]["error"])
    assert status is not None
    assert status["last_tick_at"] == "2026-06-29T08:30:00+00:00"
    assert "provider down" in str(status["last_error"])
    assert status["polls_sent"] == 0


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.anyio
async def test_debug_mode_keeps_attempt_bookkeeping_unchanged(monkeypatch):
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
            timezone="UTC",
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
                }
            ],
        )
        poll_rule = list_text_schedule_rules(conn, text_id=text_id)[0]

    sent_slots: list[str | None] = []

    async def fake_send_poll(*, scheduled_slot=None, **kwargs):
        sent_slots.append(scheduled_slot)
        return 42

    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)

    sent = await run_due_jobs(
        database_url=database_url,
        now_utc=datetime(2026, 6, 29, 8, 30, tzinfo=timezone.utc),
        debug_enabled=True,
    )

    assert sent == 2
    assert sent_slots == [f"rule:{poll_rule['id']}:poll:08:30", f"rule:{poll_rule['id']}:poll:08:30"]
    with db_session(database_url) as conn:
        attempts = conn.execute(
            "SELECT status, scheduled_slot, poll_id FROM scheduled_send_attempts ORDER BY id ASC"
        ).fetchall()
    assert [row["status"] for row in attempts] == ["sent", "sent"]
    assert [row["scheduled_slot"] for row in attempts] == sent_slots
    assert [row["poll_id"] for row in attempts] == [42, 42]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.anyio
async def test_debug_mode_redacts_secret_like_fields_in_logs(monkeypatch, tmp_path):
    database_url = reset_db()
    log_file = tmp_path / "scheduler.jsonl"
    configure_logging(
        SimpleNamespace(
            log_level="INFO",
            log_format="json",
            log_file=str(log_file),
            log_human_file="",
        )
    )
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
            timezone="UTC",
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

    async def fake_send_poll(**kwargs):
        return 9

    monkeypatch.setattr("app.scheduler.generate_and_send_poll", fake_send_poll)

    await run_due_jobs(
        database_url=database_url,
        now_utc=datetime(2026, 6, 29, 8, 30, tzinfo=timezone.utc),
        debug_enabled=True,
    )

    payloads = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    debug_payloads = [payload for payload in payloads if payload["message"].startswith("scheduler.debug.")]

    assert debug_payloads
    serialized = json.dumps(debug_payloads)
    assert "abc123" not in serialized
    assert "gemini-key" not in serialized
    assert payloads[0]["message"] in {"scheduler.debug.tick_start", "scheduler.debug.heartbeat_write", "scheduler.tick"}
    assert "[REDACTED]" in serialized
