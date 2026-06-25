from __future__ import annotations

from dataclasses import dataclass

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
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise GreenAPIError("httpx is not installed. Run `pip install -e .` first.") from exc
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self._url("sendPoll"), json=payload)
        if response.status_code >= 400:
            raise GreenAPIError(f"sendPoll failed {response.status_code}: {response.text}")
        data = response.json()
        message_id = data.get("idMessage")
        if not message_id:
            raise GreenAPIError(f"sendPoll response missing idMessage: {data}")
        return str(message_id)

    async def send_message(self, *, chat_id: str, message: str) -> str:
        payload = {"chatId": chat_id, "message": message}
        try:
            import httpx
        except ModuleNotFoundError as exc:
            raise GreenAPIError("httpx is not installed. Run `pip install -e .` first.") from exc
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self._url("sendMessage"), json=payload)
        if response.status_code >= 400:
            raise GreenAPIError(f"sendMessage failed {response.status_code}: {response.text}")
        data = response.json()
        return str(data.get("idMessage", ""))


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
