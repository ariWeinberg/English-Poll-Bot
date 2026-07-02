from __future__ import annotations

from pydantic import BaseModel, Field


class PreviewRequest(BaseModel):
    text_id: int


class SendPollRequest(BaseModel):
    text_id: int
    scheduled_slot: str | None = "manual"


class SendSummaryRequest(BaseModel):
    text_id: int | None = None


class ReadinessDetail(BaseModel):
    ok: bool
    detail: str
    observed_at: str | None = None
    last_tick_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None


class ReadinessResponse(BaseModel):
    ok: bool
    generated_at: str
    database: ReadinessDetail
    scheduler: ReadinessDetail
    warnings: list[str] = Field(default_factory=list)
