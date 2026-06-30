from app.waha import WAHAClient, WAHAConfig, WAHAError


def build_client() -> WAHAClient:
    return WAHAClient(WAHAConfig(base_url="https://waha.example", session="session-a", api_key="secret"))


async def _unexpected_request(*args, **kwargs):
    raise AssertionError(f"Unexpected request: {args} {kwargs}")


def test_waha_send_poll_uses_documented_endpoint_and_payload(monkeypatch):
    client = build_client()
    calls: list[tuple[str, str, dict | None]] = []

    async def fake_request(method: str, path: str, *, json_body=None):
        calls.append((method, path, json_body))
        return {"id": "msg-1"}

    monkeypatch.setattr(client, "_request", fake_request)

    message_id = __import__("asyncio").run(
        client.send_poll(chat_id="120363000@g.us", question="Choose one", options=["One", "Two"])
    )

    assert message_id == "msg-1"
    assert calls == [
        (
            "POST",
            "/api/sendPoll",
            {
                "session": "session-a",
                "chatId": "120363000@g.us",
                "poll": {
                    "name": "Choose one",
                    "options": ["One", "Two"],
                    "multipleAnswers": False,
                },
            },
        )
    ]


def test_waha_send_poll_normalizes_nested_message_id(monkeypatch):
    client = build_client()

    async def fake_request(method: str, path: str, *, json_body=None):
        assert method == "POST"
        assert path == "/api/sendPoll"
        assert json_body is not None
        return {
            "id": {
                "fromMe": True,
                "remote": "120363000@g.us",
                "id": "3EB0ABCDEF",
                "participant": {"_serialized": "252342767239268@lid"},
            }
        }

    monkeypatch.setattr(client, "_request", fake_request)

    message_id = __import__("asyncio").run(
        client.send_poll(chat_id="120363000@g.us", question="Choose one", options=["One", "Two"])
    )

    assert message_id == "true_120363000@g.us_3EB0ABCDEF_252342767239268@lid"


def test_waha_group_catalog_uses_groups_endpoint_and_maps_subject(monkeypatch):
    client = build_client()

    async def fake_request(method: str, path: str, *, json_body=None):
        assert method == "GET"
        assert path == "/api/session-a/groups"
        assert json_body is None
        return [
            {"id": "120363000@g.us", "subject": "Morning Group"},
            {"id": "111@c.us", "subject": "Direct"},
        ]

    monkeypatch.setattr(client, "_request", fake_request)

    chats = __import__("asyncio").run(client.get_group_chats())

    assert chats == [{"chat_id": "120363000@g.us", "name": "Morning Group"}]


def test_waha_group_catalog_accepts_nested_group_metadata_shape(monkeypatch):
    client = build_client()

    async def fake_request(method: str, path: str, *, json_body=None):
        assert method == "GET"
        assert path == "/api/session-a/groups"
        assert json_body is None
        return [
            {
                "groupMetadata": {
                    "id": {"_serialized": "13477702828-1538885447@g.us"},
                    "subject": "Sales Group",
                    "participants": [{"id": {"_serialized": "111@c.us"}}],
                }
            }
        ]

    monkeypatch.setattr(client, "_request", fake_request)

    chats = __import__("asyncio").run(client.get_group_chats())

    assert chats == [{"chat_id": "13477702828-1538885447@g.us", "name": "Sales Group"}]


def test_waha_group_participants_uses_v2_endpoint_and_maps_pn(monkeypatch):
    client = build_client()

    async def fake_request(method: str, path: str, *, json_body=None):
        assert method == "GET"
        assert path == "/api/session-a/groups/120363000@g.us/participants/v2"
        assert json_body is None
        return [
            {"id": "123456789@lid", "pn": "123456789@c.us", "role": "participant"},
            {"id": "555@c.us", "role": "admin"},
        ]

    monkeypatch.setattr(client, "_request", fake_request)

    participants = __import__("asyncio").run(client.get_group_participants(chat_id="120363000@g.us"))

    assert participants == [
        {
            "voter_wid": "123456789@c.us",
            "display_name": "participant",
            "phone_number": "123456789",
        },
        {
            "voter_wid": "555@c.us",
            "display_name": "admin",
            "phone_number": "555",
        },
    ]


def test_waha_contact_lookup_uses_documented_contact_endpoint(monkeypatch):
    client = build_client()

    async def fake_request(method: str, path: str, *, json_body=None):
        assert method == "GET"
        assert path == "/api/session-a/contacts/123456789@c.us"
        assert json_body is None
        return {"pushName": "Dana"}

    monkeypatch.setattr(client, "_request", fake_request)

    name = __import__("asyncio").run(client.get_contact_name(chat_id="123456789@c.us"))

    assert name == "Dana"


def test_waha_validate_accepts_working_session(monkeypatch):
    client = build_client()

    async def fake_request(method: str, path: str, *, json_body=None):
        assert method == "GET"
        assert path == "/api/sessions"
        assert json_body is None
        return [{"name": "session-a", "status": "WORKING"}]

    monkeypatch.setattr(client, "_request", fake_request)

    __import__("asyncio").run(client.validate())


def test_waha_validate_rejects_missing_or_unusable_session(monkeypatch):
    client = build_client()

    async def missing_request(method: str, path: str, *, json_body=None):
        assert method == "GET"
        assert path == "/api/sessions"
        assert json_body is None
        return [{"name": "other", "status": "WORKING"}]

    monkeypatch.setattr(client, "_request", missing_request)

    try:
        __import__("asyncio").run(client.validate())
    except WAHAError as exc:
        assert "was not found" in str(exc)
    else:
        raise AssertionError("Expected WAHAError for missing session")

    async def stopped_request(method: str, path: str, *, json_body=None):
        assert method == "GET"
        assert path == "/api/sessions"
        assert json_body is None
        return [{"name": "session-a", "status": "STOPPED"}]

    monkeypatch.setattr(client, "_request", stopped_request)

    try:
        __import__("asyncio").run(client.validate())
    except WAHAError as exc:
        assert "STOPPED" in str(exc)
    else:
        raise AssertionError("Expected WAHAError for unusable session")


def test_waha_parse_webhook_accepts_documented_poll_vote_payload():
    client = build_client()

    parsed = client.parse_webhook(
        {
            "event": "poll.vote",
            "payload": {
                "vote": {
                    "id": "false_120363410357828123@g.us_3EB0B0698FEF4B43922FC5",
                    "selectedOptions": ["The single word 'test'"],
                    "from": "120363410357828123@g.us",
                    "participant": "972501234567@c.us",
                    "fromMe": False,
                },
                "poll": {"id": "true_120363410357828123@g.us_3EB0B0698FEF4B43922FC5_252342767239268@lid"},
            },
        }
    )

    assert parsed is not None
    assert parsed.provider_message_id == "true_120363410357828123@g.us_3EB0B0698FEF4B43922FC5_252342767239268@lid"
    assert parsed.option_voters == {
        "The single word 'test'": [
            {
                "voter_wid": "972501234567@c.us",
                "voter_name": None,
                "phone_number": "972501234567",
            }
        ]
    }
