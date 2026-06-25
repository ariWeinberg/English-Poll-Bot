from app.greenapi import build_poll_payload


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
