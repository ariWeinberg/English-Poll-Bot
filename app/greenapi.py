from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class GreenAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class GreenAPIConfig:
    api_url: str
    id_instance: str
    api_token_instance: str


class GreenAPIClient:
    def __init__(self, config: GreenAPIConfig) -> None:
        self.config = config

    def _url(self, method: str) -> str:
        return (
            f"{self.config.api_url.rstrip('/')}/waInstance{self.config.id_instance}"
            f"/{method}/{self.config.api_token_instance}"
        )

    async def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise GreenAPIError("httpx is not installed. Run `pip install -e .` first.") from exc
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self._url(method), json=payload)
        if response.status_code >= 400:
            raise GreenAPIError(f"{method} failed {response.status_code}: {response.text}")
        data = response.json()
        if not isinstance(data, dict):
            raise GreenAPIError(f"{method} returned an unexpected payload: {data}")
        return data

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


def normalize_phone(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    base = stripped.split("@", 1)[0]
    digits = "".join(ch for ch in base if ch.isdigit())
    return digits or base
