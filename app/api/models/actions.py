from __future__ import annotations

from pydantic import BaseModel


class PreviewRequest(BaseModel):
    text_id: int


class SendPollRequest(BaseModel):
    text_id: int
    scheduled_slot: str | None = "manual"


class SendSummaryRequest(BaseModel):
    text_id: int | None = None
