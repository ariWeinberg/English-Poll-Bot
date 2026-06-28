from app.greenapi import build_poll_payload, parse_group_chat, parse_group_participant


def test_build_poll_payload_matches_greenapi_send_poll_shape():
    payload = build_poll_payload(
        chat_id="120363000@g.us",
        question="Choose one",
        options=["One", "Two"],
        multiple_answers=False,
    )

    assert payload == {
        "chatId": "120363000@g.us",
        "message": "Choose one",
        "options": [{"optionName": "One"}, {"optionName": "Two"}],
        "multipleAnswers": False,
    }


def test_parse_group_participant_normalizes_supported_shapes():
    assert parse_group_participant("111@c.us") == {
        "voter_wid": "111@c.us",
        "display_name": None,
        "phone_number": "111",
    }
    assert parse_group_participant({"participantId": "222@c.us", "name": "Dana", "phone": "222"}) == {
        "voter_wid": "222@c.us",
        "display_name": "Dana",
        "phone_number": "222",
    }
    assert parse_group_participant({"id": "", "name": "Missing"}) is None


def test_parse_group_chat_filters_non_groups_and_keeps_name():
    assert parse_group_chat({"chatId": "120363000@g.us", "name": "Morning Group"}) == {
        "chat_id": "120363000@g.us",
        "name": "Morning Group",
    }
    assert parse_group_chat({"id": "111@c.us", "name": "Direct chat"}) is None
