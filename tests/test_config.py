from pathlib import Path

from app.database import db_session, get_active_tenant, init_db, list_texts, upsert_text, upsert_tenant
from app.services import load_runtime_config


def test_init_db_seeds_default_tenant_and_text(tmp_path: Path):
    db_path = tmp_path / "bot.db"
    init_db(db_path)

    runtime = load_runtime_config(db_path)

    assert runtime.tenant_id == 1
    assert runtime.timezone == "Asia/Jerusalem"

    with db_session(db_path) as conn:
        tenant = get_active_tenant(conn)
        texts = list_texts(conn, int(tenant["id"]))

    assert tenant["name"] == "Default tenant"
    assert len(texts) == 1


def test_tenant_and_text_can_be_updated_in_db(tmp_path: Path):
    db_path = tmp_path / "bot.db"
    init_db(db_path)
    with db_session(db_path) as conn:
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

    runtime = load_runtime_config(db_path, tenant_id)

    assert runtime.tenant_name == "Tenant A"
    assert runtime.gemini_ready is True
    with db_session(db_path) as conn:
        text = conn.execute("SELECT * FROM texts WHERE id = ?", (text_id,)).fetchone()
    assert text["title"] == "Text A"
