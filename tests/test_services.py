import os

import pytest

from app.database import create_poll, db_session, init_db, poll_stats
from app.services import handle_greenapi_webhook, parse_poll_update


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def test_parse_poll_update_ignores_non_poll_payload():
    assert parse_poll_update({"typeWebhook": "incomingMessageReceived", "messageData": {}}) is None


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_handle_greenapi_webhook_replaces_vote_state():
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE")
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "UPDATE tenants SET username = %s, password = %s, greenapi_id_instance = %s, greenapi_api_token_instance = %s, gemini_api_key = %s WHERE id = 1",
            ("tenant-a", "secret", "id", "token", "gemini-key"),
        )
        poll_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Choose",
            options=["A", "B"],
            correct_option="A",
            explanation="",
            chat_id="120@g.us",
            generated_from_text="text",
            scheduled_slot="manual",
        )
        conn.execute(
            "UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id = %s",
            ("poll-message-id", poll_id),
        )

    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [
                    {"optionName": "A", "optionVoters": ["111@c.us"]},
                    {"optionName": "B", "optionVoters": ["222@c.us"]},
                ],
            },
        },
    }

    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=payload) is True
    with db_session(TEST_DATABASE_URL) as conn:
        poll = conn.execute("SELECT * FROM polls WHERE id = %s", (poll_id,)).fetchone()
        stats = poll_stats(conn, poll)

    assert stats["counts"] == {"A": 1, "B": 1}
    assert stats["correct_rate"] == 50.0
