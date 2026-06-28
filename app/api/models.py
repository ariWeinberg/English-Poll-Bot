from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


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
    poll_pool_threshold_percent: int | None = Field(default=None, ge=0, le=100)
    enabled: bool = True
    assigned_rule_ids: list[int] = Field(default_factory=list)
    new_rules: list["ScheduleRulePayload"] = Field(default_factory=list)


class ScheduleRulePayload(BaseModel):
    name: str | None = None
    delivery_type: str
    rule_type: str
    enabled: bool = True
    time: str | None = None
    weekdays: list[int] | None = None
    month_dates: list[int] | None = None
    window_start: str | None = None
    window_end: str | None = None
    count_mode: str = "fixed"
    count_value: int | None = Field(default=1, ge=1)
    count_min: int | None = Field(default=None, ge=1)
    count_max: int | None = Field(default=None, ge=1)
    label: str | None = None

    @model_validator(mode="after")
    def validate_rule(self) -> "ScheduleRulePayload":
        if self.delivery_type not in {"poll", "summary"}:
            raise ValueError("delivery_type must be poll or summary")
        if self.rule_type not in {"daily_time", "weekday_time", "month_date_time", "random_window"}:
            raise ValueError("rule_type is invalid")
        if self.count_mode not in {"fixed", "range"}:
            raise ValueError("count_mode must be fixed or range")

        if self.rule_type == "daily_time":
            if not self.time:
                raise ValueError("time is required for daily_time rules")
        elif self.rule_type == "weekday_time":
            if not self.time:
                raise ValueError("time is required for weekday_time rules")
            if not self.weekdays:
                raise ValueError("weekdays are required for weekday_time rules")
        elif self.rule_type == "month_date_time":
            if not self.time:
                raise ValueError("time is required for month_date_time rules")
            if not self.month_dates:
                raise ValueError("month_dates are required for month_date_time rules")
        elif self.rule_type == "random_window" and (not self.window_start or not self.window_end):
            raise ValueError("window_start and window_end are required for random_window rules")

        if self.count_mode == "fixed" and self.count_value is None:
            raise ValueError("count_value is required for fixed count mode")
        if self.count_mode == "range":
            if self.count_min is None or self.count_max is None:
                raise ValueError("count_min and count_max are required for range count mode")
            if self.count_min > self.count_max:
                raise ValueError("count_min must be less than or equal to count_max")
        return self


class ScheduleRuleUpdatePayload(BaseModel):
    name: str | None = None
    delivery_type: str | None = None
    rule_type: str | None = None
    enabled: bool | None = None
    time: str | None = None
    weekdays: list[int] | None = None
    month_dates: list[int] | None = None
    window_start: str | None = None
    window_end: str | None = None
    count_mode: str | None = None
    count_value: int | None = Field(default=None, ge=1)
    count_min: int | None = Field(default=None, ge=1)
    count_max: int | None = Field(default=None, ge=1)
    label: str | None = None


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


class LearnerSummary(BaseModel):
    voter_wid: str
    display_name: str
    phone_number: str
    total_counted_votes: int
    total_polls_seen: int
    correct_count: int
    incorrect_count: int
    correct_rate: float
    accepted_changes_count: int
    ignored_changes_count: int
    assigned_polls_count: int
    responded_polls_count: int
    missed_polls_count: int
    response_rate: float
    first_activity: str | None = None
    latest_activity: str | None = None


class LearnerHistoryItem(BaseModel):
    id: int
    poll_id: int
    text_id: int
    question: str
    correct_option: str
    voter_wid: str
    display_name: str
    phone_number: str
    selected_option_name: str | None = None
    previous_option_name: str | None = None
    event_type: str
    accepted: bool
    ignored_reason: str | None = None
    recorded_at: str


class LearnerMissedPollItem(BaseModel):
    poll_id: int
    text_id: int
    question: str
    sent_at: str | None = None
    recipient_snapshot_source: str | None = None
    recipient_snapshot_synced_at: str | None = None


class LearnerDetailResponse(BaseModel):
    learner: LearnerSummary
    history: list[LearnerHistoryItem]
    missed_polls: list[LearnerMissedPollItem]


class RosterMemberUpdatePayload(BaseModel):
    excluded_from_coverage: bool


class TextScheduleRuleAssignmentPayload(BaseModel):
    rule_id: int


class RosterMember(BaseModel):
    voter_wid: str
    display_name: str
    phone_number: str
    is_active_in_chat: bool
    excluded_from_coverage: bool
    last_synced_at: str | None = None


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
