from pathlib import Path

from app.database import create_poll, db_session, init_db, poll_stats
from app.services import handle_greenapi_webhook, parse_poll_update


def test_parse_poll_update_ignores_non_poll_payload():
    assert parse_poll_update({"typeWebhook": "incomingMessageReceived", "messageData": {}}) is None


def test_handle_greenapi_webhook_replaces_vote_state(tmp_path: Path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    with db_session(db_path) as conn:
        conn.execute(
            "UPDATE tenants SET greenapi_id_instance = ?, greenapi_api_token_instance = ?, gemini_api_key = ? WHERE id = 1",
            ("id", "token", "gemini-key"),
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
            "UPDATE polls SET greenapi_message_id = ?, status = 'sent' WHERE id = ?",
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

    assert handle_greenapi_webhook(db_path=db_path, payload=payload) is True
    with db_session(db_path) as conn:
        poll = conn.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
        stats = poll_stats(conn, poll)

    assert stats["counts"] == {"A": 1, "B": 1}
    assert stats["correct_rate"] == 50.0
