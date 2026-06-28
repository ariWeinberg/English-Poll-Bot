import os

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import create_poll, db_session, init_db, upsert_contact_profile
from app.main import app


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    object.__setattr__(settings, "database_url", TEST_DATABASE_URL)
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE")
    init_db(TEST_DATABASE_URL)
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
        assert login.status_code == 200


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

    assert body["total"] == 2
    assert [item["voter_wid"] for item in body["items"]] == ["111@c.us", "222@c.us"]
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
                "first_activity": "2025-12-20T08:00:00+00:00",
                "latest_activity": "2025-12-20T08:00:00+00:00",
            }
        ]

        recent = client.get("/api/v1/learners?date_from=2026-02-01", headers=headers)
        assert recent.status_code == 200
        items = recent.json()["items"]
        assert items[0]["voter_wid"] == "111@c.us"
        assert items[0]["total_counted_votes"] == 1
        assert items[0]["total_polls_seen"] == 1
        assert items[0]["correct_count"] == 1
        assert items[0]["incorrect_count"] == 0
        assert items[0]["ignored_changes_count"] == 1
        assert items[0]["first_activity"] == "2026-02-10T08:00:00+00:00"
        assert items[0]["latest_activity"] == "2026-02-11T10:00:00+00:00"
        assert items[1]["voter_wid"] == "222@c.us"


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
    assert [item["poll_id"] for item in body["history"]] == [
        poll_ids["poll_2"],
        poll_ids["poll_2"],
        poll_ids["poll_1"],
        poll_ids["poll_1"],
    ]
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
