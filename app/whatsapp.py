from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ConnectorConfig:
    provider: str
    config: dict[str, Any]


@dataclass(frozen=True)
class NormalizedPollUpdate:
    provider: str
    provider_message_id: str
    event_type: str | None
    message_type: str | None
    option_voters: dict[str, list[dict[str, str | None]]]
    raw_metadata: dict[str, Any]


def parse_connector_config_json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class WhatsAppProvider(Protocol):
    provider_name: str

    async def validate(self) -> None: ...

    async def send_poll(self, *, chat_id: str, question: str, options: list[str], multiple_answers: bool = False) -> str: ...

    async def send_message(self, *, chat_id: str, message: str) -> str: ...

    async def get_contact_name(self, *, chat_id: str) -> str | None: ...

    async def get_group_participants(self, *, chat_id: str) -> list[dict[str, str | None]]: ...

    async def get_group_chats(self) -> list[dict[str, str]]: ...

    def parse_webhook(self, payload: dict[str, Any]) -> NormalizedPollUpdate | None: ...
