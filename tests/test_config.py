import os
from importlib import reload

import pytest

import app.config as config_module
from app.database import db_session, get_active_tenant, init_db, list_texts, upsert_text, upsert_tenant
from app.services import load_runtime_config, runtime_config_from_row


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE app_config, tenant_group_chats, text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
    init_db(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


def test_init_db_seeds_only_default_tenant_on_blank_db():
    database_url = reset_db()

    runtime = load_runtime_config(database_url)

    assert runtime.tenant_id == 1
    assert runtime.timezone == "Asia/Jerusalem"

    with db_session(database_url) as conn:
        tenant = get_active_tenant(conn)
        texts = list_texts(conn, int(tenant["id"]))

    assert tenant["name"] == "Default tenant"
    assert texts == []


def test_init_db_does_not_recreate_deleted_sample_text():
    database_url = reset_db()
    with db_session(database_url) as conn:
        text_id = upsert_text(
            conn,
            text_id=None,
            tenant_id=1,
            title="Temporary text",
            body="Body",
            chat_id="group@g.us",
            enabled=True,
        )
        conn.execute("DELETE FROM texts WHERE id = %s", (text_id,))

    init_db(database_url)

    with db_session(database_url) as conn:
        texts = list_texts(conn, 1)

    assert texts == []


def test_tenant_and_text_can_be_updated_in_db():
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
                    "count_value": 1,
                }
            ],
        )

    runtime = load_runtime_config(database_url, tenant_id)

    assert runtime.tenant_name == "Tenant A"
    assert runtime.gemini_ready is True
    with db_session(database_url) as conn:
        text = conn.execute("SELECT * FROM texts WHERE id = %s", (text_id,)).fetchone()
        rules = conn.execute(
            "SELECT schedule_rules.* FROM text_schedule_rule_assignments JOIN schedule_rules ON schedule_rules.id = text_schedule_rule_assignments.rule_id WHERE text_schedule_rule_assignments.text_id = %s",
            (text_id,),
        ).fetchall()
    assert text["title"] == "Text A"
    assert len(rules) == 1


def test_init_db_shared_rule_migration_is_idempotent():
    database_url = reset_db()
    with db_session(database_url) as conn:
        conn.execute(
            """
            INSERT INTO texts (
                tenant_id, title, body, chat_id, enabled, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (1, "Legacy text", "Body", "group@g.us", True, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO text_schedule_rules (
                text_id, delivery_type, rule_type, enabled, time, weekdays_json, month_dates_json,
                window_start, window_end, count_mode, count_value, count_min, count_max, label, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                1,
                "poll",
                "daily_time",
                True,
                "08:30",
                "[]",
                "[]",
                None,
                None,
                "fixed",
                1,
                None,
                None,
                "Legacy poll",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    init_db(database_url)
    with db_session(database_url) as conn:
        first_rule_count = int(conn.execute("SELECT COUNT(*) AS count FROM schedule_rules").fetchone()["count"])
        first_assignment_count = int(
            conn.execute("SELECT COUNT(*) AS count FROM text_schedule_rule_assignments").fetchone()["count"]
        )

    init_db(database_url)
    with db_session(database_url) as conn:
        second_rule_count = int(conn.execute("SELECT COUNT(*) AS count FROM schedule_rules").fetchone()["count"])
        second_assignment_count = int(
            conn.execute("SELECT COUNT(*) AS count FROM text_schedule_rule_assignments").fetchone()["count"]
        )

    assert first_rule_count == 1
    assert first_assignment_count == 1
    assert second_rule_count == first_rule_count
    assert second_assignment_count == first_assignment_count


def test_init_db_legacy_text_timing_migrates_once_then_stops():
    database_url = reset_db()
    with db_session(database_url) as conn:
        conn.execute(
            """
            INSERT INTO texts (
                tenant_id, title, body, chat_id, morning_time, evening_time,
                summary_time_morning, summary_time_evening, enabled, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                1,
                "Migrated legacy text",
                "Body",
                "legacy@g.us",
                "09:15",
                "18:45",
                "09:10",
                "18:40",
                True,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    init_db(database_url)
    with db_session(database_url) as conn:
        first_rules = int(conn.execute("SELECT COUNT(*) AS count FROM schedule_rules").fetchone()["count"])
        first_assignments = int(
            conn.execute("SELECT COUNT(*) AS count FROM text_schedule_rule_assignments").fetchone()["count"]
        )

    init_db(database_url)
    with db_session(database_url) as conn:
        second_rules = int(conn.execute("SELECT COUNT(*) AS count FROM schedule_rules").fetchone()["count"])
        second_assignments = int(
            conn.execute("SELECT COUNT(*) AS count FROM text_schedule_rule_assignments").fetchone()["count"]
        )

    assert first_rules == 4
    assert first_assignments == 4
    assert second_rules == first_rules
    assert second_assignments == first_assignments


def test_runtime_config_accepts_scheduler_text_rows():
    runtime = runtime_config_from_row(
        {
            "id": 99,
            "tenant_id": 1,
            "tenant_name": "Tenant A",
            "greenapi_api_url": "https://api.green-api.com",
            "greenapi_id_instance": "7103000000",
            "greenapi_api_token_instance": "abc123",
            "gemini_api_key": "gemini-key",
            "gemini_model": "gemini-3.5-flash",
            "timezone": "Asia/Jerusalem",
            "summary_enabled": True,
            "scheduler_enabled": True,
        }
    )

    assert runtime.tenant_name == "Tenant A"
    assert runtime.tenant_id == 1
    assert runtime.greenapi_ready is True
    assert runtime.gemini_ready is True


def test_scheduler_debug_flag_defaults_false(monkeypatch):
    monkeypatch.delenv("SCHEDULER_DEBUG_ENABLED", raising=False)
    reload(config_module)

    assert config_module.settings.scheduler_debug_enabled is False


def test_scheduler_debug_flag_parses_true(monkeypatch):
    monkeypatch.setenv("SCHEDULER_DEBUG_ENABLED", "true")
    reload(config_module)

    assert config_module.settings.scheduler_debug_enabled is True
