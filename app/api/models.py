from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str


class DocsSessionResponse(BaseModel):
    docs_token: str
    token_type: str = "docs"
    expires_at: str
    docs_url: str
    openapi_url: str


class RegisterRequest(BaseModel):
    name: str = "Tenant"
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    timezone: str = "Asia/Jerusalem"


class TenantPayload(BaseModel):
    name: str = "Tenant"
    username: str = ""
    password: str | None = None
    greenapi_api_url: str = "https://api.green-api.com"
    greenapi_id_instance: str = ""
    greenapi_api_token_instance: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    timezone: str = "Asia/Jerusalem"
    poll_pool_threshold_percent: int = Field(default=80, ge=0, le=100)
    summary_enabled: bool = True
    scheduler_enabled: bool = True
    is_active: bool = True


class TextPayload(BaseModel):
    tenant_id: int
    title: str
    body: str
    chat_id: str
    morning_time: str = "08:30"
    evening_time: str = "18:00"
    summary_time_morning: str = "08:25"
    summary_time_evening: str = "17:55"
    poll_pool_threshold_percent: int | None = Field(default=None, ge=0, le=100)
    enabled: bool = True


class PollPayload(BaseModel):
    tenant_id: int
    text_id: int
    question: str
    options: list[str] = Field(min_length=2)
    correct_option: str
    explanation: str = ""
    greenapi_message_id: str | None = None
    chat_id: str
    generated_from_text: str = ""
    status: str = "draft"
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


class PreviewRequest(BaseModel):
    text_id: int


class SendPollRequest(BaseModel):
    text_id: int
    scheduled_slot: str | None = "manual"


class SendSummaryRequest(BaseModel):
    text_id: int | None = None


class PoolRankPayload(BaseModel):
    pool_rank: int = Field(ge=1)
