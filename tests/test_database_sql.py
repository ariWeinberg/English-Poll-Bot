from app.database import _learner_aggregate_cte
from app.db_runtime import normalize_database_url
from app.services import runtime_config_from_row


def test_learner_aggregate_cte_qualifies_change_rollup_voter_wid():
    sql = _learner_aggregate_cte("1 = 1")

    assert "SELECT\n                poll_vote_events.voter_wid," in sql
    assert "poll_vote_events.voter_wid\n                    )" in sql
    assert "split_part(poll_vote_events.voter_wid, '@', 1)" in sql


def test_normalize_database_url_uses_psycopg_driver():
    assert normalize_database_url("postgresql://postgres:postgres@db:5432/english_bot") == (
        "postgresql+psycopg://postgres:postgres@db:5432/english_bot"
    )
    assert normalize_database_url("postgres://postgres:postgres@db:5432/english_bot") == (
        "postgresql+psycopg://postgres:postgres@db:5432/english_bot"
    )


def test_runtime_config_accepts_scheduler_rows_with_waha_connector():
    runtime = runtime_config_from_row(
        {
            "id": 99,
            "tenant_id": 3,
            "tenant_name": "Tenant A",
            "whatsapp_provider": "waha",
            "whatsapp_connector": {
                "provider": "waha",
                "config": {
                    "base_url": "https://waha.example",
                    "session": "Test",
                    "api_key": "secret",
                },
            },
            "gemini_api_key": "gemini-key",
            "gemini_model": "gemini-3.5-flash",
            "timezone": "Asia/Jerusalem",
            "summary_enabled": True,
            "scheduler_enabled": True,
        }
    )

    assert runtime.tenant_id == 3
    assert runtime.tenant_name == "Tenant A"
    assert runtime.whatsapp_provider == "waha"
    assert runtime.whatsapp_ready is True
    assert runtime.gemini_ready is True
