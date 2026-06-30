from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.models.schedule_rules import ScheduleRulePayload


class TextPayload(BaseModel):
    tenant_id: int
    title: str
    body: str
    chat_id: str
    poll_pool_threshold_percent: int | None = Field(default=None, ge=0, le=100)
    enabled: bool = True
    assigned_rule_ids: list[int] = Field(default_factory=list)
    new_rules: list[ScheduleRulePayload] = Field(default_factory=list)
