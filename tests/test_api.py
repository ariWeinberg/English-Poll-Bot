import json
import os

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import create_poll, db_session, init_db, upsert_contact_profile
from app.greenapi import GreenAPIError
from app.main import app
from app.services import TextNotFoundError, WebhookDecision
from app.waha import WAHAError


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    object.__setattr__(settings, "database_url", TEST_DATABASE_URL)
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE app_config, tenant_group_chats, text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, incoming_webhooks, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            """
            INSERT INTO texts (
                tenant_id, title, body, chat_id, enabled, created_at, updated_at
            )
            VALUES (1, 'Fixture text', 'Body', 'group@g.us', TRUE, %s, %s)
            """,
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
    return TEST_DATABASE_URL


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def seed_learner_analytics_fixture(database_url: str) -> dict[str, int]:
    with db_session(database_url) as conn:
        conn.execute(
            """
            INSERT INTO texts
                (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                 summary_time_morning, summary_time_evening, enabled, created_at, updated_at)
            VALUES
                (2, 1, 'Advanced lesson', 'Body 2', 'group-2@g.us', '08:30', '18:00',
                 '08:25', '17:55', TRUE, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO tenants
                (id, name, username, password, greenapi_api_url, greenapi_id_instance,
                 greenapi_api_token_instance, gemini_api_key, gemini_model, timezone,
                 summary_enabled, scheduler_enabled, is_active, created_at, updated_at)
            VALUES
                (2, 'Tenant B', 'tenant-b', 'secret', 'https://api.green-api.com', '', '',
                 '', 'gemini-3.5-flash', 'Asia/Jerusalem', TRUE, TRUE, TRUE,
                 '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO texts
                (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                 summary_time_morning, summary_time_evening, enabled, created_at, updated_at)
            VALUES
                (3, 2, 'Tenant B text', 'Body 3', 'group-b@g.us', '08:30', '18:00',
                 '08:25', '17:55', TRUE, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )

        poll_1 = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="P1",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        poll_2 = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="P2",
            options=["A", "B"],
            correct_option="B",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        poll_3 = create_poll(
            conn,
            tenant_id=1,
            text_id=2,
            question="P3",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group-2@g.us",
            generated_from_text="Body 2",
            scheduled_slot="manual",
        )
        poll_4 = create_poll(
            conn,
            tenant_id=2,
            text_id=3,
            question="P4",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group-b@g.us",
            generated_from_text="Body 3",
            scheduled_slot="manual",
        )

        conn.execute(
            """
            UPDATE polls
            SET
                status = CASE
                    WHEN id = %s THEN 'sent'
                    WHEN id = %s THEN 'sent'
                    WHEN id = %s THEN 'sent'
                    WHEN id = %s THEN 'sent'
                END,
                sent_at = CASE
                    WHEN id = %s THEN '2026-01-10T08:00:00+00:00'
                    WHEN id = %s THEN '2026-02-10T08:00:00+00:00'
                    WHEN id = %s THEN '2025-12-20T08:00:00+00:00'
                    WHEN id = %s THEN '2026-03-01T08:00:00+00:00'
                END
            WHERE id IN (%s, %s, %s, %s)
            """,
            (poll_1, poll_2, poll_3, poll_4, poll_1, poll_2, poll_3, poll_4, poll_1, poll_2, poll_3, poll_4),
        )

        upsert_contact_profile(conn, tenant_id=1, voter_wid="111@c.us", phone_number="111", display_name="Dana Cohen")
        upsert_contact_profile(
            conn, tenant_id=2, voter_wid="111@c.us", phone_number="999", display_name="Tenant B Dana"
        )

        conn.execute(
            """
            INSERT INTO poll_votes (poll_id, option_name, voter_wid, voter_name, phone_number, first_accepted_at, updated_at)
            VALUES
                (%s, 'B', '111@c.us', 'Dana Cohen', '111', '2026-01-10T08:00:00+00:00', '2026-01-11T09:00:00+00:00'),
                (%s, 'B', '111@c.us', 'Dana Cohen', '111', '2026-02-10T08:00:00+00:00', '2026-02-10T08:00:00+00:00'),
                (%s, 'A', '111@c.us', 'Dana Cohen', '111', '2025-12-20T08:00:00+00:00', '2025-12-20T08:00:00+00:00'),
                (%s, 'B', '222@c.us', NULL, '222', '2026-02-09T08:00:00+00:00', '2026-02-09T08:00:00+00:00'),
                (%s, 'A', '111@c.us', 'Tenant B Dana', '999', '2026-03-01T08:00:00+00:00', '2026-03-01T08:00:00+00:00')
            """,
            (poll_1, poll_2, poll_3, poll_1, poll_4),
        )
        conn.execute(
            """
            INSERT INTO poll_vote_events
                (poll_id, option_name, voter_wid, voter_name, phone_number, event_type, previous_option_name, accepted, ignored_reason, recorded_at)
            VALUES
                (%s, 'A', '111@c.us', 'Dana Cohen', '111', 'vote', NULL, TRUE, NULL, '2026-01-10T08:00:00+00:00'),
                (%s, 'B', '111@c.us', 'Dana Cohen', '111', 'change', 'A', TRUE, NULL, '2026-01-11T09:00:00+00:00'),
                (%s, 'B', '111@c.us', 'Dana Cohen', '111', 'vote', NULL, TRUE, NULL, '2026-02-10T08:00:00+00:00'),
                (%s, 'A', '111@c.us', 'Dana Cohen', '111', 'change', 'B', FALSE, 'manual_lock', '2026-02-11T10:00:00+00:00'),
                (%s, 'A', '111@c.us', 'Dana Cohen', '111', 'vote', NULL, TRUE, NULL, '2025-12-20T08:00:00+00:00'),
                (%s, 'B', '222@c.us', NULL, '222', 'vote', NULL, TRUE, NULL, '2026-02-09T08:00:00+00:00'),
                (%s, 'A', '111@c.us', 'Tenant B Dana', '999', 'vote', NULL, TRUE, NULL, '2026-03-01T08:00:00+00:00')
            """,
            (poll_1, poll_1, poll_2, poll_2, poll_3, poll_1, poll_4),
        )
        conn.execute(
            """
            INSERT INTO poll_recipient_snapshots
                (poll_id, tenant_id, chat_id, voter_wid, phone_number, display_name, created_at)
            VALUES
                (%s, 1, 'group@g.us', '111@c.us', '111', 'Dana Cohen', '2026-01-10T07:59:00+00:00'),
                (%s, 1, 'group@g.us', '222@c.us', '222', NULL, '2026-01-10T07:59:00+00:00'),
                (%s, 1, 'group@g.us', '333@c.us', '333', NULL, '2026-01-10T07:59:00+00:00'),
                (%s, 1, 'group@g.us', '111@c.us', '111', 'Dana Cohen', '2026-02-10T07:59:00+00:00'),
                (%s, 1, 'group@g.us', '333@c.us', '333', NULL, '2026-02-10T07:59:00+00:00'),
                (%s, 1, 'group-2@g.us', '111@c.us', '111', 'Dana Cohen', '2025-12-20T07:59:00+00:00'),
                (%s, 1, 'group-2@g.us', '444@c.us', '444', NULL, '2025-12-20T07:59:00+00:00'),
                (%s, 2, 'group-b@g.us', '111@c.us', '999', 'Tenant B Dana', '2026-03-01T07:59:00+00:00')
            """,
            (poll_1, poll_1, poll_1, poll_2, poll_2, poll_3, poll_3, poll_4),
        )
        conn.execute(
            """
            UPDATE polls
            SET recipient_snapshot_source = 'live_sync', recipient_snapshot_synced_at = created_at
            WHERE id IN (%s, %s, %s, %s)
            """,
            (poll_1, poll_2, poll_3, poll_4),
        )

    return {"poll_1": poll_1, "poll_2": poll_2, "poll_3": poll_3, "poll_4": poll_4}


def test_register_creates_tenant_and_allows_login():
    reset_db()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Acme Learning",
                "username": "acme",
                "password": "secret123",
                "timezone": "Asia/Jerusalem",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["access_token"]

        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200
        assert me.json()["name"] == "Acme Learning"
        assert me.json()["username"] == "acme"
        assert "password" not in me.json()

        duplicate = client.post(
            "/api/v1/auth/register",
            json={"name": "Second", "username": "acme", "password": "another", "timezone": "Asia/Jerusalem"},
        )
        assert duplicate.status_code == 409

        login = client.post("/api/v1/auth/login", json={"username": "acme", "password": "secret123"})
        assert login.status_code == 200


def test_default_admin_login_works_after_password_hash_migration():
    database_url = reset_db()
    with db_session(database_url) as conn:
        tenant = conn.execute("SELECT password FROM tenants WHERE id = 1").fetchone()
    assert tenant is not None
    assert tenant["password"] != "admin"

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200


def test_inactive_tenant_login_is_rejected():
    database_url = reset_db()
    with db_session(database_url) as conn:
        conn.execute(
            """
            INSERT INTO tenants
                (id, name, username, password, greenapi_api_url, greenapi_id_instance,
                 greenapi_api_token_instance, gemini_api_key, gemini_model, timezone,
                 summary_enabled, scheduler_enabled, is_active, created_at, updated_at)
            VALUES
                (2, 'Inactive Tenant', 'inactive', 'secret', 'https://api.green-api.com', '', '',
                 '', 'gemini-3.5-flash', 'Asia/Jerusalem', TRUE, TRUE, FALSE,
                 '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username": "inactive", "password": "secret"})

    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant is inactive"


def test_authenticated_docs_session_opens_swagger_and_openapi():
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)

        session = client.post("/api/v1/docs/session", headers=headers)
        assert session.status_code == 200
        body = session.json()
        assert body["docs_token"]
        assert body["docs_url"].startswith("/api/v1/docs?token=")
        assert body["openapi_url"].startswith("/api/v1/openapi.json?token=")

        swagger = client.get(body["docs_url"])
        assert swagger.status_code == 200
        assert "Swagger UI" in swagger.text

        openapi = client.get(body["openapi_url"])
        assert openapi.status_code == 200
        assert openapi.json()["info"]["title"] == "English WhatsApp Poll Bot API"


def test_auth_and_text_pagination_filtering():
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)
        assert client.get("/api/v1/texts").status_code == 403

        for index in range(3):
            response = client.post(
                "/api/v1/texts",
                headers=headers,
                data={
                    "tenant_id": "1",
                    "title": f"Lesson {index}",
                    "body": f"Body {index}",
                    "chat_id": "group@g.us",
                    "enabled": "true" if index != 2 else "false",
                },
            )
            assert response.status_code == 201

        response = client.get("/api/v1/texts?tenant_id=1&page=1&page_size=2", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 4
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert body["has_next"] is True

        response = client.get("/api/v1/texts?tenant_id=1&enabled=false", headers=headers)
        assert response.status_code == 200
        assert [item["title"] for item in response.json()["items"]] == ["Lesson 2"]


def test_text_schedule_rule_crud_and_validation():
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)

        created = client.post(
            "/api/v1/texts",
            headers=headers,
            data={"tenant_id": "1", "title": "Rules", "body": "Body", "chat_id": "group@g.us", "enabled": "true"},
        )
        assert created.status_code == 201
        text_id = created.json()["id"]
        assert created.json()["schedule_rules"] == []

        created_rule = client.post(
            "/api/v1/schedule-rules",
            headers=headers,
            json={
                "name": "Weekday drill",
                "delivery_type": "poll",
                "rule_type": "weekday_time",
                "enabled": True,
                "time": "08:30",
                "weekdays": [0, 2, 4],
                "count_mode": "range",
                "count_min": 1,
                "count_max": 3,
                "label": "Weekday drill",
            },
        )
        assert created_rule.status_code == 201
        rule_id = created_rule.json()["id"]
        assert created_rule.json()["weekdays"] == [0, 2, 4]

        assigned = client.post(
            f"/api/v1/texts/{text_id}/schedule-rules/assign",
            headers=headers,
            json={"rule_id": rule_id},
        )
        assert assigned.status_code == 201
        assert len(assigned.json()) == 1

        listed = client.get(f"/api/v1/texts/{text_id}/schedule-rules", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        patched = client.patch(
            f"/api/v1/schedule-rules/{rule_id}",
            headers=headers,
            json={"rule_type": "month_date_time", "weekdays": [], "month_dates": [1, 15], "time": "09:00"},
        )
        assert patched.status_code == 200
        assert patched.json()["rule_type"] == "month_date_time"
        assert patched.json()["month_dates"] == [1, 15]

        invalid = client.post(
            "/api/v1/schedule-rules",
            headers=headers,
            json={
                "name": "Broken window",
                "delivery_type": "poll",
                "rule_type": "random_window",
                "enabled": True,
                "window_start": "10:00",
                "window_end": "09:00",
                "count_mode": "fixed",
                "count_value": 1,
            },
        )
        assert invalid.status_code == 422

        bad_weekday = client.post(
            "/api/v1/schedule-rules",
            headers=headers,
            json={
                "name": "Bad weekday",
                "delivery_type": "poll",
                "rule_type": "weekday_time",
                "enabled": True,
                "time": "08:30",
                "weekdays": [7],
                "count_mode": "fixed",
                "count_value": 1,
            },
        )
        assert bad_weekday.status_code == 422

        deleted = client.delete(f"/api/v1/texts/{text_id}/schedule-rules/{rule_id}", headers=headers)
        assert deleted.status_code == 204


def test_text_create_supports_assigned_rule_ids_and_inline_new_rules():
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)

        shared = client.post(
            "/api/v1/schedule-rules",
            headers=headers,
            json={
                "name": "Morning poll",
                "delivery_type": "poll",
                "rule_type": "daily_time",
                "time": "08:30",
                "count_mode": "fixed",
                "count_value": 1,
            },
        )
        assert shared.status_code == 201
        shared_id = shared.json()["id"]

        created = client.post(
            "/api/v1/texts",
            headers=headers,
            data={
                "tenant_id": "1",
                "title": "Inline rules",
                "body": "Body",
                "chat_id": "group@g.us",
                "assigned_rule_ids_json": json.dumps([shared_id]),
                "new_rules_json": json.dumps(
                    [
                        {
                            "name": "Inline summary",
                            "delivery_type": "summary",
                            "rule_type": "daily_time",
                            "time": "08:29",
                            "count_mode": "fixed",
                            "count_value": 1,
                        }
                    ]
                ),
            },
        )
        assert created.status_code == 201
        rule_names = [rule["name"] for rule in created.json()["schedule_rules"]]
        assert "Morning poll" in rule_names
        assert "Inline summary" in rule_names

        invalid = client.post(
            "/api/v1/texts",
            headers=headers,
            data={
                "tenant_id": "1",
                "title": "Broken inline",
                "body": "Body",
                "chat_id": "group@g.us",
                "new_rules_json": json.dumps([{"delivery_type": "poll", "rule_type": "weekday_time", "time": "08:30"}]),
            },
        )
        assert invalid.status_code == 422


def test_chat_catalog_routes_and_blocked_chat_rejection(monkeypatch):
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)

        async def fake_refresh(*, settings, database_url):
            del settings, database_url
            with db_session(TEST_DATABASE_URL) as conn:
                conn.execute(
                    """
                    INSERT INTO tenant_group_chats
                        (tenant_id, chat_id, name, policy, last_synced_at, created_at, updated_at)
                    VALUES
                        (1, 'group-a@g.us', 'Group A', 'neutral', '2026-06-28T12:00:00+00:00', '2026-06-28T12:00:00+00:00', '2026-06-28T12:00:00+00:00')
                    ON CONFLICT (tenant_id, chat_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        last_synced_at = EXCLUDED.last_synced_at,
                        updated_at = EXCLUDED.updated_at
                    """
                )
                return conn.execute(
                    "SELECT chat_id, name, policy, last_synced_at FROM tenant_group_chats WHERE tenant_id = 1"
                ).fetchall()

        monkeypatch.setattr("app.api.routes.chats.refresh_tenant_group_chats", fake_refresh)

        refreshed = client.post("/api/v1/chats/refresh", headers=headers)
        assert refreshed.status_code == 200
        assert refreshed.json()[0]["chat_id"] == "group-a@g.us"

        updated = client.patch("/api/v1/chats/group-a@g.us/policy", headers=headers, json={"policy": "block"})
        assert updated.status_code == 200
        assert updated.json()["policy"] == "block"

        blocked_text = client.post(
            "/api/v1/texts",
            headers=headers,
            data={"tenant_id": "1", "title": "Blocked", "body": "Body", "chat_id": "group-a@g.us", "enabled": "true"},
        )
        assert blocked_text.status_code == 422


def test_send_now_returns_structured_provider_errors(monkeypatch):
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)

        async def raise_waha(*, settings, database_url, text_id, scheduled_slot):
            del settings, database_url, text_id, scheduled_slot
            raise WAHAError("WAHA upstream unavailable")

        monkeypatch.setattr("app.api.routes.actions.generate_and_send_poll", raise_waha)

        response = client.post(
            "/api/v1/polls/send-now",
            headers=headers,
            json={"text_id": 1, "scheduled_slot": "manual"},
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "WAHA upstream unavailable"

        async def raise_greenapi(*, settings, database_url, text_id, scheduled_slot):
            del settings, database_url, text_id, scheduled_slot
            raise GreenAPIError("GreenAPI rejected sendPoll")

        monkeypatch.setattr("app.api.routes.actions.generate_and_send_poll", raise_greenapi)

        response = client.post(
            "/api/v1/polls/send-now",
            headers=headers,
            json={"text_id": 1, "scheduled_slot": "manual"},
        )
        assert response.status_code == 502
        assert response.json()["detail"] == "GreenAPI rejected sendPoll"


def test_send_now_keeps_400_for_config_and_404_for_missing_text(monkeypatch):
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)

        async def raise_missing(*, settings, database_url, text_id, scheduled_slot):
            del settings, database_url, text_id, scheduled_slot
            raise TextNotFoundError("Text not found.")

        monkeypatch.setattr("app.api.routes.actions.generate_and_send_poll", raise_missing)

        response = client.post(
            "/api/v1/polls/send-now",
            headers=headers,
            json={"text_id": 999, "scheduled_slot": "manual"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Text not found."

        async def raise_config(*, settings, database_url, text_id, scheduled_slot):
            del settings, database_url, text_id, scheduled_slot
            raise ValueError("WhatsApp connector configuration is incomplete.")

        monkeypatch.setattr("app.api.routes.actions.generate_and_send_poll", raise_config)

        response = client.post(
            "/api/v1/polls/send-now",
            headers=headers,
            json={"text_id": 1, "scheduled_slot": "manual"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "WhatsApp connector configuration is incomplete."


def test_poll_update_persists_question_review_state():
    database_url = reset_db()
    with db_session(database_url) as conn:
        poll_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Review me?",
            options=["A", "B", "C", "D"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
            status="draft",
        )

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.patch(
            f"/api/v1/polls/{poll_id}",
            headers=headers,
            json={
                "tenant_id": 1,
                "text_id": 1,
                "question": "Review me?",
                "options": ["A", "B", "C", "D"],
                "correct_option": "A",
                "explanation": "",
                "provider": None,
                "provider_message_id": None,
                "greenapi_message_id": None,
                "chat_id": "group@g.us",
                "generated_from_text": "Body",
                "status": "draft",
                "review_status": "needs_edit",
                "review_notes": "The distractors are too easy.",
                "scheduled_slot": "manual",
                "sent_at": None,
                "summary_sent_at": None,
                "pool_rank": None,
                "change_window_seconds": None,
                "manual_lock": False,
                "auto_lock_seconds": None,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["review_status"] == "needs_edit"
        assert body["review_notes"] == "The distractors are too easy."

        detail = client.get(f"/api/v1/polls/{poll_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["review_status"] == "needs_edit"
        assert detail.json()["review_notes"] == "The distractors are too easy."


def test_poll_quality_summary_and_review_filter_returns_quality_queue():
    database_url = reset_db()
    poll_ids = seed_learner_analytics_fixture(database_url)
    with db_session(database_url) as conn:
        conn.execute(
            """
            UPDATE polls
            SET review_status = CASE
                WHEN id = %s THEN 'approved'
                WHEN id = %s THEN 'needs_edit'
                WHEN id = %s THEN 'draft'
            END
            WHERE id IN (%s, %s, %s)
            """,
            (poll_ids["poll_1"], poll_ids["poll_2"], poll_ids["poll_3"], poll_ids["poll_1"], poll_ids["poll_2"], poll_ids["poll_3"]),
        )

    with TestClient(app) as client:
        headers = auth_headers(client)
        summary = client.get("/api/v1/polls/quality-summary", headers=headers)
        filtered = client.get("/api/v1/polls?status=sent&review_status=needs_edit", headers=headers)

    assert summary.status_code == 200
    body = summary.json()
    assert body["total_polls"] == 3
    assert body["draft_count"] == 1
    assert body["approved_count"] == 1
    assert body["needs_edit_count"] == 1
    assert body["review_required_count"] == 2
    assert body["low_accuracy_count"] == 1
    assert [item["poll"]["id"] for item in body["weakest_polls"]] == [poll_ids["poll_1"], poll_ids["poll_2"], poll_ids["poll_3"]]

    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert [item["id"] for item in filtered_body["items"]] == [poll_ids["poll_2"]]
    assert filtered_body["items"][0]["review_status"] == "needs_edit"


def test_tenant_routes_hide_password_and_blank_update_keeps_existing_login():
    reset_db()
    with TestClient(app) as client:
        headers = auth_headers(client)
        created = client.post(
            "/api/v1/tenants",
            headers=headers,
            json={
                "name": "Workspace",
                "username": "workspace",
                "password": "initial-secret",
                "greenapi_api_url": "https://api.green-api.com",
                "greenapi_id_instance": "",
                "greenapi_api_token_instance": "",
                "gemini_api_key": "",
                "gemini_model": "gemini-3.5-flash",
                "timezone": "Asia/Jerusalem",
                "summary_enabled": True,
                "scheduler_enabled": True,
                "is_active": False,
            },
        )
        assert created.status_code == 201
        tenant = created.json()
        assert "password" not in tenant

        listing = client.get("/api/v1/tenants", headers=headers)
        assert listing.status_code == 200
        assert all("password" not in item for item in listing.json()["items"])

        detail = client.get(f"/api/v1/tenants/{tenant['id']}", headers=headers)
        assert detail.status_code == 200
        assert "password" not in detail.json()

        updated = client.patch(
            f"/api/v1/tenants/{tenant['id']}",
            headers=headers,
            json={
                "name": "Workspace Updated",
                "username": "workspace",
                "password": "",
                "greenapi_api_url": "https://api.green-api.com",
                "greenapi_id_instance": "",
                "greenapi_api_token_instance": "",
                "gemini_api_key": "",
                "gemini_model": "gemini-3.5-flash",
                "timezone": "Asia/Jerusalem",
                "summary_enabled": True,
                "scheduler_enabled": True,
                "is_active": False,
            },
        )
        assert updated.status_code == 200
        assert "password" not in updated.json()

        login = client.post("/api/v1/auth/login", json={"username": "workspace", "password": "initial-secret"})
        assert login.status_code == 403


def test_register_keeps_existing_active_tenants_active():
    database_url = reset_db()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "name": "Acme Learning",
                "username": "acme",
                "password": "secret123",
                "timezone": "Asia/Jerusalem",
            },
        )
        assert response.status_code == 201

        admin_login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
        assert admin_login.status_code == 200

    with db_session(database_url) as conn:
        tenants = conn.execute("SELECT username, is_active FROM tenants ORDER BY id ASC").fetchall()

    assert tenants == [
        {"username": "admin", "is_active": True},
        {"username": "acme", "is_active": True},
    ]


def test_greenapi_webhook_is_tenant_scoped():
    database_url = reset_db()
    with db_session(database_url) as conn:
        conn.execute(
            """
            INSERT INTO tenants
                (id, name, username, password, greenapi_api_url, greenapi_id_instance,
                 greenapi_api_token_instance, gemini_api_key, gemini_model, timezone,
                 summary_enabled, scheduler_enabled, is_active, created_at, updated_at)
            VALUES
                (2, 'Tenant B', 'tenant-b', 'secret', 'https://api.green-api.com', '', '',
                 '', 'gemini-3.5-flash', 'Asia/Jerusalem', TRUE, TRUE, FALSE, 'now', 'now')
            """
        )
        conn.execute(
            """
            INSERT INTO texts
                (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                 summary_time_morning, summary_time_evening, enabled, created_at, updated_at)
            VALUES
                (2, 2, 'Tenant B text', 'Body', 'group@g.us', '08:30', '18:00',
                 '08:25', '17:55', TRUE, 'now', 'now')
            """
        )
        poll_a = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Choose A",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        poll_b = create_poll(
            conn,
            tenant_id=2,
            text_id=2,
            question="Choose B",
            options=["A", "B"],
            correct_option="B",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        conn.execute(
            "UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id IN (%s, %s)",
            ("same-id", poll_a, poll_b),
        )

    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "same-id",
                "votes": [{"optionName": "B", "optionVoters": ["222@c.us"]}],
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/webhooks/greenapi/2", json=payload)
        assert response.status_code == 200
        assert response.json()["handled"] is True

        headers = auth_headers(client)
        response = client.get("/api/v1/poll-vote-events?tenant_id=2&page_size=10", headers=headers)
        assert response.status_code == 200
        events = response.json()["items"]
        assert events == [
            {
                "id": 1,
                "poll_id": poll_b,
                "option_name": "B",
                "voter_wid": "222@c.us",
                "voter_name": None,
                "phone_number": "222",
                "event_type": "vote",
                "previous_option_name": None,
                "recorded_at": events[0]["recorded_at"],
            }
        ]

    with db_session(database_url) as conn:
        rows = conn.execute("SELECT poll_id, option_name FROM poll_votes ORDER BY poll_id").fetchall()
    assert rows == [{"poll_id": poll_b, "option_name": "B"}]


def test_webhook_inbox_records_accepted_poll_update():
    database_url = reset_db()
    with db_session(database_url) as conn:
        poll_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Choose",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        conn.execute(
            "UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id = %s",
            ("accepted-message-id", poll_id),
        )

    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "accepted-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }
    raw_payload = json.dumps(payload)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/greenapi/1",
            content=raw_payload,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "handled": True}

    with db_session(database_url) as conn:
        row = conn.execute("SELECT * FROM incoming_webhooks ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["tenant_id"] == 1
    assert row["provider"] == "greenapi"
    assert row["endpoint_path"] == "/webhooks/greenapi/1"
    assert row["type_webhook"] == "incomingMessageReceived"
    assert row["message_type"] == "pollUpdateMessage"
    assert row["greenapi_message_id"] == "accepted-message-id"
    assert row["poll_id"] == poll_id
    assert row["decision_status"] == "accepted"
    assert row["decision_reason"] == "handled"
    assert row["payload_json"] == raw_payload
    assert row["processed_at"] is not None
    assert row["error"] is None


def test_webhook_inbox_records_ignored_non_poll_payload():
    database_url = reset_db()
    payload = {"typeWebhook": "incomingMessageReceived", "messageData": {"typeMessage": "textMessage"}}
    raw_payload = json.dumps(payload)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/greenapi/1",
            content=raw_payload,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "handled": False}

    with db_session(database_url) as conn:
        row = conn.execute("SELECT * FROM incoming_webhooks ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["decision_status"] == "ignored"
    assert row["decision_reason"] == "not_poll_update"
    assert row["payload_json"] == raw_payload


def test_webhook_inbox_records_ignored_unknown_message_id():
    database_url = reset_db()
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "missing-poll-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }

    with TestClient(app) as client:
        response = client.post("/webhooks/greenapi/1", json=payload)
    assert response.status_code == 200
    assert response.json()["handled"] is False

    with db_session(database_url) as conn:
        row = conn.execute("SELECT * FROM incoming_webhooks ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["decision_status"] == "ignored"
    assert row["decision_reason"] == "poll_not_found"
    assert row["greenapi_message_id"] == "missing-poll-message-id"


def test_webhook_inbox_records_processing_exception(monkeypatch):
    database_url = reset_db()

    async def broken_handler(*, database_url: str, payload: dict[str, object], tenant_id: int | None = None):
        del database_url, payload, tenant_id
        raise RuntimeError("webhook exploded")

    monkeypatch.setattr("app.api.routes.actions.handle_greenapi_webhook_async", broken_handler)

    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "broken-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/webhooks/greenapi/1", json=payload)
    assert response.status_code == 500

    with db_session(database_url) as conn:
        row = conn.execute("SELECT * FROM incoming_webhooks ORDER BY id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["decision_status"] == "error"
    assert row["decision_reason"] == "webhook exploded"
    assert row["error"] == "webhook exploded"
    assert row["greenapi_message_id"] == "broken-message-id"


def test_webhook_retry_reprocesses_errored_event(monkeypatch):
    database_url = reset_db()

    async def broken_handler(*, database_url: str, payload: dict[str, object], tenant_id: int | None = None):
        del database_url, payload, tenant_id
        raise RuntimeError("webhook exploded")

    async def recovered_handler(*, database_url: str, payload: dict[str, object], tenant_id: int | None = None):
        del database_url, payload, tenant_id
        return WebhookDecision(
            handled=True,
            status="accepted",
            reason="handled",
            provider="greenapi",
            type_webhook="incomingMessageReceived",
            message_type="pollUpdateMessage",
            provider_message_id="broken-message-id",
            greenapi_message_id="broken-message-id",
            provider_metadata={"source": "retry"},
            poll_id=None,
            error=None,
        )

    monkeypatch.setattr("app.api.routes.actions.handle_greenapi_webhook_async", broken_handler)

    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "broken-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/webhooks/greenapi/1", json=payload)
        assert response.status_code == 500

        with db_session(database_url) as conn:
            row = conn.execute("SELECT id, decision_status, retry_count FROM incoming_webhooks ORDER BY id DESC LIMIT 1").fetchone()
        webhook_id = int(row["id"])
        assert row["decision_status"] == "error"
        assert int(row["retry_count"]) == 0

        monkeypatch.setattr("app.api.routes.actions.handle_greenapi_webhook_async", recovered_handler)
        headers = auth_headers(client)
        retry = client.post(f"/api/v1/webhooks/{webhook_id}/retry", headers=headers)

    assert retry.status_code == 200
    assert retry.json() == {"ok": True, "retried": True}

    with db_session(database_url) as conn:
        row = conn.execute(
            "SELECT decision_status, decision_reason, retry_count, last_retry_at, last_retry_error, error FROM incoming_webhooks WHERE id = %s",
            (webhook_id,),
        ).fetchone()
    assert row["decision_status"] == "accepted"
    assert row["decision_reason"] == "handled"
    assert int(row["retry_count"]) == 1
    assert row["last_retry_at"] is not None
    assert row["last_retry_error"] is None
    assert row["error"] is None


def test_webhook_inbox_list_and_detail_are_tenant_scoped_and_filterable():
    database_url = reset_db()
    with db_session(database_url) as conn:
        conn.execute(
            """
            INSERT INTO tenants
                (id, name, username, password, greenapi_api_url, greenapi_id_instance,
                 greenapi_api_token_instance, gemini_api_key, gemini_model, timezone,
                 summary_enabled, scheduler_enabled, is_active, created_at, updated_at)
            VALUES
                (2, 'Tenant B', 'tenant-b', 'secret', 'https://api.green-api.com', '', '',
                 '', 'gemini-3.5-flash', 'Asia/Jerusalem', TRUE, TRUE, TRUE,
                 '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            INSERT INTO texts
                (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                 summary_time_morning, summary_time_evening, enabled, created_at, updated_at)
            VALUES
                (2, 2, 'Tenant B text', 'Body', 'group-b@g.us', '08:30', '18:00',
                 '08:25', '17:55', TRUE, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """
        )
        poll_a = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Tenant A poll",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        poll_b = create_poll(
            conn,
            tenant_id=2,
            text_id=2,
            question="Tenant B poll",
            options=["A", "B"],
            correct_option="B",
            explanation="",
            chat_id="group-b@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        conn.execute(
            "UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id = %s",
            ("tenant-a-message-id", poll_a),
        )
        conn.execute(
            "UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id = %s",
            ("tenant-b-message-id", poll_b),
        )

    accepted_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "tenant-a-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }
    ignored_payload = {"typeWebhook": "incomingMessageReceived", "messageData": {"typeMessage": "textMessage"}}
    missing_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "missing-webhook-poll",
                "votes": [{"optionName": "B", "optionVoters": ["111@c.us"]}],
            },
        },
    }
    tenant_b_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "tenant-b-message-id",
                "votes": [{"optionName": "B", "optionVoters": ["222@c.us"]}],
            },
        },
    }

    with TestClient(app) as client:
        assert client.post("/webhooks/greenapi/1", json=accepted_payload).status_code == 200
        assert client.post("/webhooks/greenapi/1", json=ignored_payload).status_code == 200
        assert client.post("/webhooks/greenapi/1", json=missing_payload).status_code == 200
        assert client.post("/webhooks/greenapi/2", json=tenant_b_payload).status_code == 200

        with db_session(database_url) as conn:
            rows = conn.execute(
                "SELECT id, decision_reason FROM incoming_webhooks WHERE tenant_id = 1 ORDER BY id ASC"
            ).fetchall()
            accepted_id = int(rows[0]["id"])
            ignored_id = int(rows[1]["id"])
            missing_id = int(rows[2]["id"])
            conn.execute(
                """
                UPDATE incoming_webhooks
                SET received_at = CASE
                    WHEN id = %s THEN '2026-06-10T08:00:00+00:00'
                    WHEN id = %s THEN '2026-06-11T08:00:00+00:00'
                    WHEN id = %s THEN '2026-06-12T08:00:00+00:00'
                    ELSE received_at
                END,
                processed_at = CASE
                    WHEN tenant_id = 1 THEN '2026-06-12T09:00:00+00:00'
                    ELSE processed_at
                END
                WHERE tenant_id IN (1, 2)
                """,
                (accepted_id, ignored_id, missing_id),
            )

        headers = auth_headers(client)

        listing = client.get("/api/v1/webhooks?page_size=10", headers=headers)
        assert listing.status_code == 200
        assert listing.json()["total"] == 3
        assert {item["decision_status"] for item in listing.json()["items"]} == {"accepted", "ignored"}

        accepted_only = client.get("/api/v1/webhooks?status=accepted", headers=headers)
        assert accepted_only.status_code == 200
        assert accepted_only.json()["total"] == 1
        assert accepted_only.json()["items"][0]["poll_id"] == poll_a

        reason_filtered = client.get("/api/v1/webhooks?reason=not_poll_update", headers=headers)
        assert reason_filtered.status_code == 200
        assert reason_filtered.json()["items"][0]["decision_reason"] == "not_poll_update"

        type_filtered = client.get("/api/v1/webhooks?type_webhook=incomingMessageReceived", headers=headers)
        assert type_filtered.status_code == 200
        assert type_filtered.json()["total"] == 3

        message_filtered = client.get("/api/v1/webhooks?greenapi_message_id=tenant-a-message-id", headers=headers)
        assert message_filtered.status_code == 200
        assert message_filtered.json()["items"][0]["greenapi_message_id"] == "tenant-a-message-id"

        poll_filtered = client.get(f"/api/v1/webhooks?poll_id={poll_a}", headers=headers)
        assert poll_filtered.status_code == 200
        assert poll_filtered.json()["items"][0]["poll_id"] == poll_a

        search_filtered = client.get("/api/v1/webhooks?search=poll_not_found", headers=headers)
        assert search_filtered.status_code == 200
        assert search_filtered.json()["items"][0]["decision_reason"] == "poll_not_found"

        dated = client.get("/api/v1/webhooks?date_from=2026-06-11&date_to=2026-06-11", headers=headers)
        assert dated.status_code == 200
        assert dated.json()["total"] == 1
        assert dated.json()["items"][0]["id"] == ignored_id

        detail = client.get(f"/api/v1/webhooks/{accepted_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["id"] == accepted_id
        assert detail.json()["payload_json"] == json.dumps(accepted_payload)

        missing_detail = client.get("/api/v1/webhooks/999999", headers=headers)
        assert missing_detail.status_code == 404


def test_poll_vote_status_route_returns_counted_and_ignored_state():
    database_url = reset_db()
    with db_session(database_url) as conn:
        poll_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Choose",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
            change_window_seconds=60,
            manual_lock=False,
            auto_lock_seconds=300,
        )
        conn.execute(
            """
            INSERT INTO poll_votes (poll_id, option_name, voter_wid, voter_name, phone_number, first_accepted_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (poll_id, "A", "111@c.us", "Dana Cohen", "111", "2026-01-01T12:00:00+00:00", "2026-01-01T12:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO poll_vote_events
                (poll_id, option_name, voter_wid, voter_name, phone_number, event_type, previous_option_name, accepted, ignored_reason, recorded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                poll_id,
                "B",
                "111@c.us",
                "Dana Cohen",
                "111",
                "change",
                "A",
                False,
                "change_window_expired",
                "2026-01-01T12:02:00+00:00",
            ),
        )

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.get(f"/api/v1/polls/{poll_id}/vote-status", headers=headers)
        assert response.status_code == 200
        assert response.json() == [
            {
                "poll_id": poll_id,
                "voter_wid": "111@c.us",
                "voter_name": "Dana Cohen",
                "phone_number": "111",
                "counted_option_name": "A",
                "first_accepted_at": "2026-01-01T12:00:00+00:00",
                "updated_at": "2026-01-01T12:00:00+00:00",
                "latest_ignored_option_name": "B",
                "latest_ignored_reason": "change_window_expired",
                "latest_ignored_at": "2026-01-01T12:02:00+00:00",
            }
        ]


def test_learners_leaderboard_is_tenant_scoped_and_aggregated():
    database_url = reset_db()
    seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.get("/api/v1/learners?page_size=10", headers=headers)
        assert response.status_code == 200
        body = response.json()

    assert body["total"] == 4
    assert [item["voter_wid"] for item in body["items"]] == ["111@c.us", "222@c.us", "333@c.us", "444@c.us"]
    assert body["items"][0] == {
        "voter_wid": "111@c.us",
        "display_name": "Dana Cohen",
        "phone_number": "111",
        "total_counted_votes": 4,
        "total_polls_seen": 3,
        "correct_count": 3,
        "incorrect_count": 1,
        "correct_rate": 75.0,
        "accepted_changes_count": 1,
        "ignored_changes_count": 1,
        "assigned_polls_count": 3,
        "responded_polls_count": 3,
        "missed_polls_count": 0,
        "response_rate": 100.0,
        "first_activity": "2025-12-20T08:00:00+00:00",
        "latest_activity": "2026-02-11T10:00:00+00:00",
    }


def test_learners_filters_apply_text_and_date_ranges():
    database_url = reset_db()
    seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        text_only = client.get("/api/v1/learners?text_id=2", headers=headers)
        assert text_only.status_code == 200
        assert text_only.json()["items"] == [
            {
                "voter_wid": "111@c.us",
                "display_name": "Dana Cohen",
                "phone_number": "111",
                "total_counted_votes": 1,
                "total_polls_seen": 1,
                "correct_count": 1,
                "incorrect_count": 0,
                "correct_rate": 100.0,
                "accepted_changes_count": 0,
                "ignored_changes_count": 0,
                "assigned_polls_count": 1,
                "responded_polls_count": 1,
                "missed_polls_count": 0,
                "response_rate": 100.0,
                "first_activity": "2025-12-20T08:00:00+00:00",
                "latest_activity": "2025-12-20T08:00:00+00:00",
            },
            {
                "voter_wid": "444@c.us",
                "display_name": "444",
                "phone_number": "444",
                "total_counted_votes": 0,
                "total_polls_seen": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "correct_rate": 0.0,
                "accepted_changes_count": 0,
                "ignored_changes_count": 0,
                "assigned_polls_count": 1,
                "responded_polls_count": 0,
                "missed_polls_count": 1,
                "response_rate": 0.0,
                "first_activity": "2025-12-20T08:00:00+00:00",
                "latest_activity": "2025-12-20T08:00:00+00:00",
            },
        ]

        recent = client.get("/api/v1/learners?date_from=2026-02-01", headers=headers)
        assert recent.status_code == 200
        items = recent.json()["items"]
        assert items[0]["voter_wid"] == "111@c.us"
        assert items[0]["total_counted_votes"] == 1
        assert items[0]["total_polls_seen"] == 1
        assert items[0]["assigned_polls_count"] == 1
        assert items[0]["responded_polls_count"] == 1
        assert items[0]["missed_polls_count"] == 0
        assert items[0]["response_rate"] == 100.0
        assert items[0]["correct_count"] == 1
        assert items[0]["incorrect_count"] == 0
        assert items[0]["ignored_changes_count"] == 1
        assert items[0]["first_activity"] == "2026-02-10T08:00:00+00:00"
        assert items[0]["latest_activity"] == "2026-02-11T10:00:00+00:00"
        assert items[1]["voter_wid"] == "222@c.us"
        assert items[2]["voter_wid"] == "333@c.us"
        assert items[2]["missed_polls_count"] == 1


def test_learners_summary_returns_kpis_segments_and_ranked_slices():
    database_url = reset_db()
    seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.get("/api/v1/learners/summary", headers=headers)
        assert response.status_code == 200
        body = response.json()

    assert body["learners_total"] == 4
    assert body["assigned_polls_total"] == 7
    assert body["responded_polls_total"] == 4
    assert body["missed_polls_total"] == 3
    assert body["response_rate"] == pytest.approx(57.14, abs=0.01)
    assert body["total_counted_votes"] == 5
    assert body["correct_rate"] == 80.0
    assert body["ignored_changes_total"] == 1
    assert body["low_confidence_count"] == 3
    assert body["needs_attention_count"] == 3
    assert body["inactive_count"] == 2
    assert body["engaged_count"] == 1
    assert [item["voter_wid"] for item in body["top_missed"]] == ["333@c.us", "444@c.us", "222@c.us", "111@c.us"]
    assert [item["voter_wid"] for item in body["lowest_response"]] == ["333@c.us", "444@c.us", "222@c.us", "111@c.us"]
    assert [item["voter_wid"] for item in body["most_active"]] == ["111@c.us", "222@c.us", "333@c.us", "444@c.us"]
    assert body["top_missed"][0]["focus_area"] == "Assigned polls but no responses yet"
    assert body["top_missed"][0]["data_confidence"] == "low"
    assert body["lowest_response"][2]["focus_area"] == "Review ignored change attempts"
    assert body["most_active"][0]["data_confidence"] == "medium"


def test_learners_segment_filter_matches_backend_definitions():
    database_url = reset_db()
    seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        needs_attention = client.get("/api/v1/learners?segment=needs_attention", headers=headers)
        inactive = client.get("/api/v1/learners?segment=inactive", headers=headers)
        engaged = client.get("/api/v1/learners?segment=engaged", headers=headers)

    assert needs_attention.status_code == 200
    assert [item["voter_wid"] for item in needs_attention.json()["items"]] == ["222@c.us", "333@c.us", "444@c.us"]
    assert inactive.status_code == 200
    assert [item["voter_wid"] for item in inactive.json()["items"]] == ["333@c.us", "444@c.us"]
    assert engaged.status_code == 200
    assert [item["voter_wid"] for item in engaged.json()["items"]] == ["111@c.us"]


def test_learner_detail_returns_recent_history_with_accepted_and_ignored_state():
    database_url = reset_db()
    poll_ids = seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.get("/api/v1/learners/111@c.us?history_limit=4", headers=headers)
        assert response.status_code == 200
        body = response.json()

    assert body["learner"]["voter_wid"] == "111@c.us"
    assert body["learner"]["accepted_changes_count"] == 1
    assert body["learner"]["ignored_changes_count"] == 1
    assert body["learner"]["assigned_polls_count"] == 3
    assert body["learner"]["responded_polls_count"] == 3
    assert body["learner"]["missed_polls_count"] == 0
    assert body["learner"]["response_rate"] == 100.0
    assert body["learner"]["focus_area"] == "Review ignored change attempts"
    assert body["learner"]["data_confidence"] == "medium"
    assert [item["poll_id"] for item in body["history"]] == [
        poll_ids["poll_2"],
        poll_ids["poll_2"],
        poll_ids["poll_1"],
        poll_ids["poll_1"],
    ]
    assert body["missed_polls"] == []
    assert body["history"][0] == {
        "id": body["history"][0]["id"],
        "poll_id": poll_ids["poll_2"],
        "text_id": 1,
        "question": "P2",
        "correct_option": "B",
        "voter_wid": "111@c.us",
        "display_name": "Dana Cohen",
        "phone_number": "111",
        "selected_option_name": "A",
        "previous_option_name": "B",
        "event_type": "change",
        "accepted": False,
        "ignored_reason": "manual_lock",
        "recorded_at": "2026-02-11T10:00:00+00:00",
    }


def test_learner_detail_includes_recent_missed_polls():
    database_url = reset_db()
    poll_ids = seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.get("/api/v1/learners/333@c.us?history_limit=4&missed_limit=4", headers=headers)
        assert response.status_code == 200
        body = response.json()

    assert body["learner"]["voter_wid"] == "333@c.us"
    assert body["learner"]["assigned_polls_count"] == 2
    assert body["learner"]["responded_polls_count"] == 0
    assert body["learner"]["missed_polls_count"] == 2
    assert body["learner"]["response_rate"] == 0.0
    assert body["learner"]["focus_area"] == "Assigned polls but no responses yet"
    assert body["learner"]["data_confidence"] == "low"
    assert body["history"] == []
    assert [item["poll_id"] for item in body["missed_polls"]] == [poll_ids["poll_2"], poll_ids["poll_1"]]
    assert body["missed_polls"][0]["recipient_snapshot_source"] == "live_sync"


def test_text_roster_and_poll_coverage_routes():
    database_url = reset_db()
    poll_ids = seed_learner_analytics_fixture(database_url)
    with db_session(database_url) as conn:
        conn.execute(
            """
            INSERT INTO chat_participants
                (tenant_id, chat_id, voter_wid, phone_number, display_name, is_active_in_chat,
                 excluded_from_coverage, last_synced_at, created_at, updated_at)
            VALUES
                (1, 'group@g.us', '111@c.us', '111', 'Dana Cohen', TRUE, FALSE, '2026-02-10T07:59:00+00:00', '2026-02-10T07:59:00+00:00', '2026-02-10T07:59:00+00:00'),
                (1, 'group@g.us', '222@c.us', '222', NULL, TRUE, FALSE, '2026-02-10T07:59:00+00:00', '2026-02-10T07:59:00+00:00', '2026-02-10T07:59:00+00:00'),
                (1, 'group@g.us', '333@c.us', '333', NULL, TRUE, TRUE, '2026-02-10T07:59:00+00:00', '2026-02-10T07:59:00+00:00', '2026-02-10T07:59:00+00:00')
            """
        )

    with TestClient(app) as client:
        headers = auth_headers(client)
        roster = client.get("/api/v1/texts/1/roster", headers=headers)
        assert roster.status_code == 200
        roster_body = roster.json()
        assert roster_body["active_count"] == 3
        assert roster_body["excluded_count"] == 1
        assert roster_body["items"][0]["last_synced_at"] == "2026-02-10T07:59:00+00:00"

        toggled = client.patch(
            "/api/v1/texts/1/roster/222@c.us",
            headers=headers,
            json={"excluded_from_coverage": True},
        )
        assert toggled.status_code == 200
        assert toggled.json()["excluded_from_coverage"] is True

        coverage = client.get(f"/api/v1/polls/{poll_ids['poll_1']}/coverage", headers=headers)
        assert coverage.status_code == 200
        coverage_body = coverage.json()

    assert coverage_body["coverage_available"] is True
    assert coverage_body["recipient_snapshot_source"] == "live_sync"
    assert coverage_body["assigned_count"] == 3
    assert coverage_body["responded_count"] == 2
    assert coverage_body["missed_count"] == 1
    assert coverage_body["response_rate"] == pytest.approx(66.67, abs=0.01)
    assert coverage_body["items"] == [
        {
            "voter_wid": "333@c.us",
            "display_name": "333",
            "phone_number": "333",
            "assigned_at": "2026-01-10T07:59:00+00:00",
        }
    ]


def test_learner_routes_do_not_leak_cross_tenant_contact_collisions():
    database_url = reset_db()
    seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.get("/api/v1/learners/111@c.us", headers=headers)
        assert response.status_code == 200
        body = response.json()
        forbidden = client.get("/api/v1/learners?tenant_id=2", headers=headers)

    assert body["learner"]["display_name"] == "Dana Cohen"
    assert all(item["display_name"] == "Dana Cohen" for item in body["history"])
    assert all(item["phone_number"] == "111" for item in body["history"])
    assert forbidden.status_code == 403


def test_poll_stats_support_text_and_date_filters_with_tenant_isolation():
    database_url = reset_db()
    poll_ids = seed_learner_analytics_fixture(database_url)

    with TestClient(app) as client:
        headers = auth_headers(client)
        filtered = client.get("/api/v1/polls/stats?text_id=1&date_from=2026-02-01&date_to=2026-02-28", headers=headers)
        forbidden = client.get("/api/v1/polls/stats?tenant_id=2", headers=headers)

    assert filtered.status_code == 200
    body = filtered.json()
    assert [item["poll"]["id"] for item in body] == [poll_ids["poll_2"]]
    assert body[0]["total"] == 1
    assert body[0]["correct_rate"] == 100.0
    assert forbidden.status_code == 403


def test_bi_analytics_date_filters_fall_back_to_created_at_when_sent_at_is_missing():
    database_url = reset_db()
    with db_session(database_url) as conn:
        poll_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Created fallback poll",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
        )
        conn.execute(
            "UPDATE polls SET status = 'sent', sent_at = NULL, created_at = %s WHERE id = %s",
            ("2026-06-29T08:00:00+00:00", poll_id),
        )
        conn.execute(
            """
            INSERT INTO poll_recipient_snapshots
                (poll_id, tenant_id, chat_id, voter_wid, phone_number, display_name, created_at)
            VALUES
                (%s, 1, 'group@g.us', '111@c.us', '111', 'Dana Cohen', '2026-06-29T07:59:00+00:00')
            """,
            (poll_id,),
        )
        conn.execute(
            """
            INSERT INTO poll_votes (poll_id, option_name, voter_wid, voter_name, phone_number, first_accepted_at, updated_at)
            VALUES (%s, 'A', '111@c.us', 'Dana Cohen', '111', '2026-06-29T08:05:00+00:00', '2026-06-29T08:05:00+00:00')
            """,
            (poll_id,),
        )

    with TestClient(app) as client:
        headers = auth_headers(client)
        stats = client.get("/api/v1/polls/stats?date_from=2026-06-29&date_to=2026-06-29", headers=headers)
        learners = client.get("/api/v1/learners?date_from=2026-06-29&date_to=2026-06-29", headers=headers)

    assert stats.status_code == 200
    assert [item["poll"]["id"] for item in stats.json()] == [poll_id]
    assert learners.status_code == 200
    assert [item["voter_wid"] for item in learners.json()["items"]] == ["111@c.us"]


def test_text_enable_disable_routes_flip_only_enabled_and_keep_text_visible():
    reset_db()

    with TestClient(app) as client:
        headers = auth_headers(client)
        before = client.get("/api/v1/texts/1", headers=headers)
        disabled = client.post("/api/v1/texts/1/disable", headers=headers)
        filtered_enabled = client.get("/api/v1/texts?tenant_id=1&enabled=true", headers=headers)
        filtered_disabled = client.get("/api/v1/texts?tenant_id=1&enabled=false", headers=headers)
        enabled = client.post("/api/v1/texts/1/enable", headers=headers)

    assert before.status_code == 200
    assert disabled.status_code == 200
    assert enabled.status_code == 200
    assert before.json()["title"] == disabled.json()["title"] == enabled.json()["title"]
    assert disabled.json()["enabled"] is False
    assert enabled.json()["enabled"] is True
    assert [item["id"] for item in filtered_enabled.json()["items"]] == []
    assert [item["id"] for item in filtered_disabled.json()["items"]] == [1]


def test_tenant_pool_policy_fields_round_trip():
    reset_db()

    with TestClient(app) as client:
        headers = auth_headers(client)
        tenant = client.get("/api/v1/auth/me", headers=headers).json()
        response = client.patch(
            "/api/v1/tenants/1",
            headers=headers,
            json={
                **tenant,
                "password": "",
                "poll_pool_target_size": 14,
                "poll_pool_refill_batch_size": 6,
                "poll_pool_refill_threshold_percent": 35,
            },
        )
        refreshed = client.get("/api/v1/tenants/1", headers=headers)

    assert response.status_code == 200
    assert refreshed.status_code == 200
    assert response.json()["poll_pool_target_size"] == 14
    assert response.json()["poll_pool_refill_batch_size"] == 6
    assert response.json()["poll_pool_refill_threshold_percent"] == 35
    assert refreshed.json()["poll_pool_target_size"] == 14
    assert refreshed.json()["poll_pool_refill_batch_size"] == 6
    assert refreshed.json()["poll_pool_refill_threshold_percent"] == 35


def test_text_roster_sync_returns_updated_contact_data(monkeypatch):
    reset_db()

    async def fake_sync_text_roster(*, settings, database_url: str, text_id: int, provider=None):
        del settings, database_url, provider
        return {
            "text_id": text_id,
            "chat_id": "group@g.us",
            "last_synced_at": "2026-06-30T10:00:00+00:00",
            "active_count": 2,
            "excluded_count": 1,
            "items": [
                {
                    "voter_wid": "111@c.us",
                    "display_name": "Dana",
                    "phone_number": "111",
                    "is_active_in_chat": True,
                    "excluded_from_coverage": False,
                    "last_synced_at": "2026-06-30T10:00:00+00:00",
                },
                {
                    "voter_wid": "222@c.us",
                    "display_name": "Ilan",
                    "phone_number": "222",
                    "is_active_in_chat": True,
                    "excluded_from_coverage": True,
                    "last_synced_at": "2026-06-30T10:00:00+00:00",
                },
            ],
        }

    monkeypatch.setattr("app.api.routes.texts.sync_text_roster", fake_sync_text_roster)

    with TestClient(app) as client:
        headers = auth_headers(client)
        response = client.post("/api/v1/texts/1/roster/sync", headers=headers)

    assert response.status_code == 200
    assert response.json()["active_count"] == 2
    assert response.json()["excluded_count"] == 1
    assert response.json()["items"][0]["display_name"] == "Dana"
