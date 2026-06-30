from __future__ import annotations

from pydantic import BaseModel


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


class LearnerSummaryResponse(BaseModel):
    learners_total: int
    assigned_polls_total: int
    responded_polls_total: int
    missed_polls_total: int
    response_rate: float
    total_counted_votes: int
    correct_rate: float
    ignored_changes_total: int
    needs_attention_count: int
    inactive_count: int
    engaged_count: int
    top_missed: list[LearnerSummary]
    lowest_response: list[LearnerSummary]
    most_active: list[LearnerSummary]


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
