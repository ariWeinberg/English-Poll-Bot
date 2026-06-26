import os

import pytest

from app.database import db_session, get_active_tenant, init_db, list_texts, upsert_text, upsert_tenant
from app.services import load_runtime_config


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE")
    init_db(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


def test_init_db_seeds_default_tenant_and_text():
    database_url = reset_db()

    runtime = load_runtime_config(database_url)

    assert runtime.tenant_id == 1
    assert runtime.timezone == "Asia/Jerusalem"

    with db_session(database_url) as conn:
        tenant = get_active_tenant(conn)
        texts = list_texts(conn, int(tenant["id"]))

    assert tenant["name"] == "Default tenant"
    assert len(texts) == 1


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
            morning_time="08:30",
            evening_time="18:00",
            summary_time_morning="08:25",
            summary_time_evening="17:55",
            enabled=True,
        )

    runtime = load_runtime_config(database_url, tenant_id)

    assert runtime.tenant_name == "Tenant A"
    assert runtime.gemini_ready is True
    with db_session(database_url) as conn:
        text = conn.execute("SELECT * FROM texts WHERE id = %s", (text_id,)).fetchone()
    assert text["title"] == "Text A"
