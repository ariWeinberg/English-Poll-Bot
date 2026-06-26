import os

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import create_poll, db_session, init_db
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
        conn.execute("UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id IN (%s, %s)", ("same-id", poll_a, poll_b))

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
        assert events == [{"id": 1, "poll_id": poll_b, "option_name": "B", "voter_wid": "222@c.us", "recorded_at": events[0]["recorded_at"]}]

    with db_session(database_url) as conn:
        rows = conn.execute("SELECT poll_id, option_name FROM poll_votes ORDER BY poll_id").fetchall()
    assert rows == [{"poll_id": poll_b, "option_name": "B"}]
