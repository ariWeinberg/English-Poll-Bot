from __future__ import annotations

from pydantic import BaseModel, Field


class PollPayload(BaseModel):
    tenant_id: int
    text_id: int
    question: str
    options: list[str] = Field(min_length=2)
    correct_option: str
    explanation: str = ""
    provider: str | None = None
    provider_message_id: str | None = None
    greenapi_message_id: str | None = None
    chat_id: str
    generated_from_text: str = ""
    status: str = "draft"
    review_status: str = "draft"
    review_notes: str = ""
    scheduled_slot: str | None = None
    sent_at: str | None = None
    summary_sent_at: str | None = None
    pool_rank: int | None = Field(default=None, ge=1)
    change_window_seconds: int | None = Field(default=None, ge=0)
    manual_lock: bool = False
    auto_lock_seconds: int | None = Field(default=None, ge=0)


class PollVotePayload(BaseModel):
    poll_id: int
    option_name: str
    voter_wid: str
    voter_name: str | None = None
    phone_number: str | None = None


class PollRankPayload(BaseModel):
    pool_rank: int = Field(ge=1)


class PollCoverageItem(BaseModel):
    voter_wid: str
    display_name: str
    phone_number: str
    assigned_at: str | None = None


class PollCoverageResponse(BaseModel):
    poll_id: int
    coverage_available: bool
    recipient_snapshot_source: str | None = None
    recipient_snapshot_synced_at: str | None = None
    assigned_count: int
    responded_count: int
    missed_count: int
    response_rate: float
    items: list[PollCoverageItem]
    total: int
    page: int
    page_size: int
    has_next: bool
