from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.greenapi import normalize_phone
from app.whatsapp import NormalizedPollUpdate


class WAHAError(RuntimeError):
    pass


@dataclass(frozen=True)
class WAHAConfig:
    base_url: str
    session: str
    api_key: str = ""


class WAHAClient:
    provider_name = "waha"

    def __init__(self, config: WAHAConfig) -> None:
        self.config = config

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key.strip():
            headers["X-Api-Key"] = self.config.api_key.strip()
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.base_url.rstrip('/')}{path}"

    async def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> Any:
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise WAHAError("httpx is not installed. Run `pip install -e .` first.") from exc
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, self._url(path), json=json_body, headers=self._headers)
        if response.status_code >= 400:
            raise WAHAError(f"{method} {path} failed {response.status_code}: {response.text}")
        if not response.content:
            return {}
        return response.json()

    async def validate(self) -> None:
        data = await self._request("GET", "/api/sessions")
        if not isinstance(data, list):
            raise WAHAError("WAHA validation failed: /api/sessions did not return a list")
        session_row = next(
            (item for item in data if isinstance(item, dict) and item.get("name") == self.config.session), None
        )
        if session_row is None:
            raise WAHAError(f"WAHA validation failed: session {self.config.session!r} was not found")
        status = str(session_row.get("status") or "").strip().upper()
        if status != "WORKING":
            raise WAHAError(
                f"WAHA validation failed: session {self.config.session!r} is in {status or 'UNKNOWN'} status"
            )

    async def send_poll(
        self,
        *,
        chat_id: str,
        question: str,
        options: list[str],
        multiple_answers: bool = False,
    ) -> str:
        data = await self._request(
            "POST",
            "/api/sendPoll",
            json_body={
                "session": self.config.session,
                "chatId": chat_id,
                "poll": {
                    "name": question,
                    "options": options,
                    "multipleAnswers": multiple_answers,
                },
            },
        )
        if not isinstance(data, dict):
            raise WAHAError(f"WAHA send poll returned an unexpected payload: {data}")
        message_id = data.get("id") or data.get("messageId") or data.get("message", {}).get("id")
        if not message_id:
            raise WAHAError(f"WAHA send poll response missing message ID: {data}")
        return str(message_id)

    async def send_message(self, *, chat_id: str, message: str) -> str:
        data = await self._request(
            "POST",
            "/api/messages/text",
            json_body={"session": self.config.session, "chatId": chat_id, "text": message},
        )
        if not isinstance(data, dict):
            raise WAHAError(f"WAHA send message returned an unexpected payload: {data}")
        return str(data.get("id") or data.get("messageId") or "")

    async def get_contact_name(self, *, chat_id: str) -> str | None:
        data = await self._request(
            "GET",
            f"/api/{self.config.session}/contacts/{chat_id}",
        )
        if not isinstance(data, dict):
            return None
        for key in ("name", "pushName", "shortName"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        return None

    async def get_group_participants(self, *, chat_id: str) -> list[dict[str, str | None]]:
        data = await self._request(
            "GET",
            f"/api/{self.config.session}/groups/{chat_id}/participants/v2",
        )
        if not isinstance(data, list):
            raise WAHAError(f"WAHA group lookup returned an unexpected payload: {data}")
        rows: list[dict[str, str | None]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            voter_wid = str(item.get("pn") or item.get("id") or "").strip()
            if not voter_wid:
                continue
            rows.append(
                {
                    "voter_wid": voter_wid,
                    "display_name": str(item.get("name") or item.get("pushName") or item.get("role") or "").strip()
                    or None,
                    "phone_number": normalize_phone(str(item.get("pn") or item.get("id") or voter_wid)),
                }
            )
        return rows

    async def get_group_chats(self) -> list[dict[str, str]]:
        data = await self._request("GET", f"/api/{self.config.session}/groups")
        if not isinstance(data, list):
            raise WAHAError(f"WAHA group list returned an unexpected payload: {data}")
        chats: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            chat_id = str(item.get("id") or "").strip()
            if not chat_id.endswith("@g.us"):
                continue
            chats.append({"chat_id": chat_id, "name": str(item.get("subject") or chat_id).strip()})
        return chats

    def parse_webhook(self, payload: dict[str, Any]) -> NormalizedPollUpdate | None:
        event = str(payload.get("event") or payload.get("type") or "").strip() or None
        message = payload.get("message") if isinstance(payload.get("message"), dict) else payload
        poll = message.get("poll") if isinstance(message, dict) and isinstance(message.get("poll"), dict) else message
        provider_message_id = str(
            poll.get("messageId") or poll.get("id") or payload.get("messageId") or payload.get("id") or ""
        ).strip()
        votes = poll.get("votes") if isinstance(poll, dict) else None
        if not provider_message_id or not isinstance(votes, list):
            return None
        option_voters: dict[str, list[dict[str, str | None]]] = {}
        for vote in votes:
            if not isinstance(vote, dict):
                continue
            option_name = str(vote.get("optionName") or vote.get("option") or "").strip()
            voters = vote.get("voters") if isinstance(vote.get("voters"), list) else []
            if not option_name:
                continue
            option_voters[option_name] = [
                {
                    "voter_wid": str(item.get("id") or item.get("wid") or item.get("chatId") or "").strip(),
                    "voter_name": str(item.get("name") or item.get("pushName") or "").strip() or None,
                    "phone_number": str(item.get("phoneNumber") or "").strip()
                    or normalize_phone(str(item.get("id") or item.get("wid") or item.get("chatId") or "")),
                }
                for item in voters
                if isinstance(item, dict) and str(item.get("id") or item.get("wid") or item.get("chatId") or "").strip()
            ]
        if not option_voters:
            return None
        return NormalizedPollUpdate(
            provider=self.provider_name,
            provider_message_id=provider_message_id,
            event_type=event,
            message_type="pollVote",
            option_voters=option_voters,
            raw_metadata={"event": event},
        )
