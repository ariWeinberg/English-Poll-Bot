import os

import pytest

from app.database import create_poll, create_poll_vote, db_session, delete_poll_vote, get_poll_vote, init_db, poll_stats
from app.services import handle_greenapi_webhook, parse_poll_update


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def test_parse_poll_update_ignores_non_poll_payload():
    assert parse_poll_update({"typeWebhook": "incomingMessageReceived", "messageData": {}}) is None


def test_parse_poll_update_extracts_contact_name_and_phone():
    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [
                    {
                        "optionName": "A",
                        "optionVoters": [
                            {
                                "voterWid": "972501234567@c.us",
                                "contactName": "Dana Cohen",
                                "phoneNumber": "972501234567",
                            }
                        ],
                    }
                ],
            },
        },
    }

    parsed = parse_poll_update(payload)
    assert parsed == (
        "poll-message-id",
        {
            "A": [
                {
                    "voter_wid": "972501234567@c.us",
                    "voter_name": "Dana Cohen",
                    "phone_number": "972501234567",
                }
            ]
        },
    )


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_handle_greenapi_webhook_ignores_changes_after_change_window(monkeypatch):
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
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
            change_window_seconds=60,
        )
        conn.execute(
            "UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id = %s",
            ("poll-message-id", poll_id),
        )

    first_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }
    second_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [{"optionName": "B", "optionVoters": ["111@c.us"]}],
            },
        },
    }

    values = iter(["2026-01-01T12:00:00+00:00", "2026-01-01T12:02:00+00:00"])
    monkeypatch.setattr("app.database.now_iso", lambda: next(values))

    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=first_payload) is True
    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=second_payload) is True

    with db_session(TEST_DATABASE_URL) as conn:
        poll = conn.execute("SELECT * FROM polls WHERE id = %s", (poll_id,)).fetchone()
        stats = poll_stats(conn, poll)
        rows = conn.execute(
            """
            SELECT option_name, event_type, accepted, ignored_reason, previous_option_name
            FROM poll_vote_events
            WHERE poll_id = %s
            ORDER BY id
            """,
            (poll_id,),
        ).fetchall()

    assert stats["counts"] == {"A": 1, "B": 0}
    assert rows == [
        {
            "option_name": "A",
            "event_type": "vote",
            "accepted": True,
            "ignored_reason": None,
            "previous_option_name": None,
        },
        {
            "option_name": "B",
            "event_type": "change",
            "accepted": False,
            "ignored_reason": "change_window_expired",
            "previous_option_name": "A",
        },
    ]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_handle_greenapi_webhook_fetches_contact_name_from_greenapi(monkeypatch):
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "UPDATE tenants SET greenapi_id_instance = %s, greenapi_api_token_instance = %s WHERE id = 1",
            ("id", "token"),
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
            "UPDATE polls SET greenapi_message_id = %s, status = 'sent' WHERE id = %s", ("poll-message-id", poll_id)
        )

    async def fake_get_contact_name(self, *, chat_id: str):
        assert chat_id == "111@c.us"
        return "Dana Cohen"

    monkeypatch.setattr("app.greenapi.GreenAPIClient.get_contact_name", fake_get_contact_name)

    payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }

    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=payload) is True

    with db_session(TEST_DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT voter_name FROM poll_votes WHERE poll_id = %s AND voter_wid = %s", (poll_id, "111@c.us")
        ).fetchone()
        cached = conn.execute(
            "SELECT display_name FROM contact_profiles WHERE tenant_id = 1 AND voter_wid = %s", ("111@c.us",)
        ).fetchone()

    assert row == {"voter_name": "Dana Cohen"}
    assert cached == {"display_name": "Dana Cohen"}


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_handle_greenapi_webhook_accumulates_votes_across_delta_updates():
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
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

    first_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }
    second_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [{"optionName": "B", "optionVoters": ["222@c.us"]}],
            },
        },
    }

    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=first_payload) is True
    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=second_payload) is True
    with db_session(TEST_DATABASE_URL) as conn:
        poll = conn.execute("SELECT * FROM polls WHERE id = %s", (poll_id,)).fetchone()
        stats = poll_stats(conn, poll)

    assert stats["counts"] == {"A": 1, "B": 1}
    assert stats["correct_rate"] == 50.0


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_handle_greenapi_webhook_records_vote_history_when_vote_changes():
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
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

    first_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [{"optionName": "A", "optionVoters": ["111@c.us"]}],
            },
        },
    }
    second_payload = {
        "typeWebhook": "incomingMessageReceived",
        "messageData": {
            "typeMessage": "pollUpdateMessage",
            "pollMessageData": {
                "stanzaId": "poll-message-id",
                "votes": [{"optionName": "B", "optionVoters": ["111@c.us"]}],
            },
        },
    }

    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=first_payload) is True
    assert handle_greenapi_webhook(database_url=TEST_DATABASE_URL, payload=second_payload) is True

    with db_session(TEST_DATABASE_URL) as conn:
        rows = conn.execute(
            """
            SELECT option_name, voter_wid, voter_name, phone_number, event_type, previous_option_name, accepted, ignored_reason
            FROM poll_vote_events
            WHERE poll_id = %s
            ORDER BY id
            """,
            (poll_id,),
        ).fetchall()

    assert rows == [
        {
            "option_name": "A",
            "voter_wid": "111@c.us",
            "voter_name": None,
            "phone_number": "111",
            "event_type": "vote",
            "previous_option_name": None,
            "accepted": True,
            "ignored_reason": None,
        },
        {
            "option_name": "B",
            "voter_wid": "111@c.us",
            "voter_name": None,
            "phone_number": "111",
            "event_type": "change",
            "previous_option_name": "A",
            "accepted": True,
            "ignored_reason": None,
        },
    ]


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")
def test_delete_poll_vote_records_unvote_event():
    assert TEST_DATABASE_URL is not None
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute(
            "TRUNCATE text_schedule_rule_random_plans, text_schedule_rule_assignments, schedule_rules, text_schedule_rules, chat_participants, poll_recipient_snapshots, poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE"
        )
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
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
        vote_id = create_poll_vote(conn, poll_id=poll_id, option_name="A", voter_wid="111@c.us")
        assert get_poll_vote(conn, vote_id) is not None
        delete_poll_vote(conn, vote_id)

    with db_session(TEST_DATABASE_URL) as conn:
        rows = conn.execute(
            """
            SELECT option_name, voter_wid, voter_name, phone_number, event_type, previous_option_name, accepted, ignored_reason
            FROM poll_vote_events
            WHERE poll_id = %s
            ORDER BY id
            """,
            (poll_id,),
        ).fetchall()

    assert rows == [
        {
            "option_name": "A",
            "voter_wid": "111@c.us",
            "voter_name": None,
            "phone_number": "111",
            "event_type": "vote",
            "previous_option_name": None,
            "accepted": True,
            "ignored_reason": None,
        },
        {
            "option_name": "",
            "voter_wid": "111@c.us",
            "voter_name": None,
            "phone_number": "111",
            "event_type": "unvote",
            "previous_option_name": "A",
            "accepted": True,
            "ignored_reason": None,
        },
    ]
