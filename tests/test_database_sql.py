from app.database import _learner_aggregate_cte, create_poll, get_whatsapp_connector_diagnostics, update_poll
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


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConnectorConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "ORDER BY received_at DESC" in sql:
            return _FakeResult(
                {
                    "received_at": "2026-07-02T09:00:00+00:00",
                    "decision_status": "accepted",
                    "decision_reason": "handled",
                    "type_webhook": "pollMessageWebhook",
                    "message_type": "vote",
                    "provider_message_id": "abc-123",
                }
            )
        return _FakeResult(
            {
                "total": 3,
                "accepted": 1,
                "ignored": 1,
                "errored": 1,
            }
        )


def test_connector_diagnostics_include_recent_webhook_activity():
    conn = _FakeConnectorConnection()

    diagnostics = get_whatsapp_connector_diagnostics(conn, tenant_id=1, provider="waha")

    assert diagnostics["provider"] == "waha"
    assert diagnostics["last_webhook_at"] == "2026-07-02T09:00:00+00:00"
    assert diagnostics["last_webhook_status"] == "accepted"
    assert diagnostics["webhooks_last_24h"] == 3
    assert diagnostics["accepted_last_24h"] == 1
    assert diagnostics["ignored_last_24h"] == 1
    assert diagnostics["errored_last_24h"] == 1


class _PollCaptureResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _PollCaptureConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if "RETURNING id" in sql:
            return _PollCaptureResult({"id": 9})
        return _PollCaptureResult(None)


def test_poll_sql_includes_review_state_fields():
    conn = _PollCaptureConnection()

    poll_id = create_poll(
        conn,
        tenant_id=1,
        text_id=2,
        question="Review me?",
        options=["A", "B", "C", "D"],
        correct_option="A",
        explanation="",
        chat_id="group@g.us",
        generated_from_text="Body",
        scheduled_slot="manual",
        review_status="needs_edit",
        review_notes="Needs better distractors.",
    )
    update_poll(
        conn,
        poll_id=poll_id,
        tenant_id=1,
        text_id=2,
        question="Review me?",
        options=["A", "B", "C", "D"],
        correct_option="A",
        explanation="",
        greenapi_message_id=None,
        provider=None,
        provider_message_id=None,
        chat_id="group@g.us",
        generated_from_text="Body",
        status="draft",
        review_status="approved",
        review_notes="Approved after edit.",
        scheduled_slot="manual",
        sent_at=None,
        summary_sent_at=None,
        pool_rank=None,
        change_window_seconds=None,
        manual_lock=False,
        auto_lock_seconds=None,
    )

    insert_sql, insert_params = conn.calls[0]
    update_sql, update_params = conn.calls[1]

    assert "review_status" in insert_sql
    assert "review_notes" in insert_sql
    assert insert_params[10] == "needs_edit"
    assert insert_params[11] == "Needs better distractors."
    assert "review_status = %s" in update_sql
    assert "review_notes = %s" in update_sql
    assert update_params[12] == "approved"
    assert update_params[13] == "Approved after edit."
