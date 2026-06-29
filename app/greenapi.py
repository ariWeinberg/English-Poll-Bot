from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.whatsapp import NormalizedPollUpdate


class GreenAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class GreenAPIConfig:
    api_url: str
    id_instance: str
    api_token_instance: str


class GreenAPIClient:
    provider_name = "greenapi"

    def __init__(self, config: GreenAPIConfig) -> None:
        self.config = config

    def _url(self, method: str) -> str:
        return (
            f"{self.config.api_url.rstrip('/')}/waInstance{self.config.id_instance}"
            f"/{method}/{self.config.api_token_instance}"
        )

    async def _post_json(self, method: str, payload: dict[str, Any]) -> Any:
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise GreenAPIError("httpx is not installed. Run `pip install -e .` first.") from exc
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self._url(method), json=payload)
        if response.status_code >= 400:
            raise GreenAPIError(f"{method} failed {response.status_code}: {response.text}")
        return response.json()

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = await self._post_json(method, payload)
        if not isinstance(data, dict):
            raise GreenAPIError(f"{method} returned an unexpected payload: {data}")
        return data

    async def validate(self) -> None:
        await self._post("getStateInstance", {})

    async def send_poll(
        self,
        *,
        chat_id: str,
        question: str,
        options: list[str],
        multiple_answers: bool = False,
    ) -> str:
        payload = build_poll_payload(
            chat_id=chat_id,
            question=question,
            options=options,
            multiple_answers=multiple_answers,
        )
        data = await self._post("sendPoll", payload)
        message_id = data.get("idMessage")
        if not message_id:
            raise GreenAPIError(f"sendPoll response missing idMessage: {data}")
        return str(message_id)

    async def send_message(self, *, chat_id: str, message: str) -> str:
        payload = {"chatId": chat_id, "message": message}
        data = await self._post("sendMessage", payload)
        return str(data.get("idMessage", ""))

    async def get_contact_name(self, *, chat_id: str) -> str | None:
        data = await self._post("getContactInfo", {"chatId": chat_id})
        for key in ("name", "contactName", "pushname", "pushName"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return None

    async def get_group_participants(self, *, chat_id: str) -> list[dict[str, str | None]]:
        data = await self._post("getGroupData", {"groupId": chat_id})
        raw_items = data.get("participants") or data.get("members") or data.get("group") or []
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("participants") or raw_items.get("members") or []
        if not isinstance(raw_items, list):
            raise GreenAPIError(f"getGroupData returned an unexpected participants payload: {data}")
        return [participant for item in raw_items if (participant := parse_group_participant(item)) is not None]

    async def get_group_chats(self) -> list[dict[str, str]]:
        data = await self._post_json("getChats", {})
        raw_items: Any = data
        if isinstance(raw_items, dict):
            raw_items = (
                raw_items.get("chats")
                or raw_items.get("items")
                or raw_items.get("data")
                or raw_items.get("results")
                or []
            )
        if not isinstance(raw_items, list):
            raise GreenAPIError(f"getChats returned an unexpected payload: {data}")
        chats: list[dict[str, str]] = []
        for item in raw_items:
            parsed = parse_group_chat(item)
            if parsed is not None:
                chats.append(parsed)
        return chats

    def parse_webhook(self, payload: dict[str, Any]) -> NormalizedPollUpdate | None:
        poll_data = _extract_poll_message_data(payload)
        if poll_data is None:
            return None
        stanza_id = poll_data.get("stanzaId") or poll_data.get("idMessage") or poll_data.get("messageId")
        votes = _extract_poll_votes(poll_data.get("votes"))
        if not stanza_id or not votes:
            return None
        option_voters: dict[str, list[dict[str, str | None]]] = {}
        for vote in votes:
            option = str(vote.get("optionName", "")).strip()
            raw_voters = vote.get("optionVoters")
            if raw_voters is None:
                raw_voters = vote.get("voters")
            if raw_voters is None:
                raw_voters = vote.get("participants")
            voters = raw_voters if isinstance(raw_voters, list) else []
            if option:
                option_voters[option] = [
                    record for voter in voters if (record := _parse_voter_record(voter)) is not None
                ]
        if not option_voters:
            return None
        return NormalizedPollUpdate(
            provider=self.provider_name,
            provider_message_id=str(stanza_id),
            event_type=str(payload.get("typeWebhook") or "").strip() or None,
            message_type=_extract_message_type(payload),
            option_voters=option_voters,
            raw_metadata={},
        )


def build_poll_payload(
    *,
    chat_id: str,
    question: str,
    options: list[str],
    multiple_answers: bool,
) -> dict:
    return {
        "chatId": chat_id,
        "message": question,
        "options": [{"optionName": option} for option in options],
        "multipleAnswers": multiple_answers,
    }


def parse_group_participant(value: Any) -> dict[str, str | None] | None:
    if isinstance(value, str):
        voter_wid = value.strip()
        if not voter_wid:
            return None
        return {
            "voter_wid": voter_wid,
            "display_name": None,
            "phone_number": normalize_phone(voter_wid),
        }
    if not isinstance(value, dict):
        return None
    voter_wid = str(
        value.get("chatId")
        or value.get("id")
        or value.get("participant")
        or value.get("participantId")
        or value.get("wid")
        or ""
    ).strip()
    if not voter_wid:
        return None
    display_name = (
        str(
            value.get("name") or value.get("contactName") or value.get("pushName") or value.get("pushname") or ""
        ).strip()
        or None
    )
    phone_number = str(value.get("phoneNumber") or value.get("phone") or "").strip() or normalize_phone(voter_wid)
    return {
        "voter_wid": voter_wid,
        "display_name": display_name,
        "phone_number": phone_number,
    }


def parse_group_chat(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    chat_id = str(
        value.get("chatId") or value.get("id") or value.get("groupId") or value.get("wid") or value.get("chat") or ""
    ).strip()
    if not chat_id.endswith("@g.us"):
        return None
    name = str(
        value.get("name")
        or value.get("subject")
        or value.get("title")
        or value.get("groupName")
        or value.get("chatName")
        or chat_id
    ).strip()
    return {"chat_id": chat_id, "name": name or chat_id}


def normalize_phone(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    base = stripped.split("@", 1)[0]
    digits = "".join(ch for ch in base if ch.isdigit())
    return digits or base


def _parse_voter_record(value: Any) -> dict[str, str | None] | None:
    if isinstance(value, str):
        voter_wid = value.strip()
        if not voter_wid:
            return None
        return {
            "voter_wid": voter_wid,
            "voter_name": None,
            "phone_number": normalize_phone(voter_wid),
        }
    if not isinstance(value, dict):
        return None
    voter_wid = str(
        value.get("voterWid")
        or value.get("wid")
        or value.get("voterId")
        or value.get("chatId")
        or value.get("id")
        or ""
    ).strip()
    if not voter_wid:
        return None
    voter_name = (
        str(
            value.get("contactName") or value.get("senderName") or value.get("name") or value.get("pushName") or ""
        ).strip()
        or None
    )
    phone_number = str(value.get("phoneNumber") or value.get("phone") or "").strip() or normalize_phone(voter_wid)
    return {
        "voter_wid": voter_wid,
        "voter_name": voter_name,
        "phone_number": phone_number,
    }


def _extract_poll_message_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    top_level_poll = payload.get("pollMessageData")
    if isinstance(top_level_poll, dict):
        return top_level_poll
    candidates: list[Any] = [
        payload.get("messageData"),
        payload.get("editedMessageData"),
        payload.get("quotedMessageData"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if isinstance(candidate.get("pollMessageData"), dict):
            return candidate["pollMessageData"]
        if candidate.get("typeMessage") == "pollUpdateMessage":
            return candidate
    return None


def _extract_poll_votes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nested = value.get("votes") or value.get("items") or value.get("results")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        rows: list[dict[str, Any]] = []
        for option_name, voters in value.items():
            if isinstance(option_name, str):
                rows.append({"optionName": option_name, "optionVoters": voters})
        return rows
    return []


def _extract_message_type(payload: dict[str, Any]) -> str | None:
    for candidate in (
        payload.get("messageData"),
        payload.get("editedMessageData"),
        payload.get("quotedMessageData"),
        payload,
    ):
        if isinstance(candidate, dict):
            raw_message_type = candidate.get("typeMessage")
            if isinstance(raw_message_type, str) and raw_message_type.strip():
                return raw_message_type.strip()
    return None
