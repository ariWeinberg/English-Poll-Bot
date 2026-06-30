from __future__ import annotations

from pydantic import BaseModel


class RosterMemberUpdatePayload(BaseModel):
    excluded_from_coverage: bool


class RosterMember(BaseModel):
    voter_wid: str
    display_name: str
    phone_number: str
    is_active_in_chat: bool
    excluded_from_coverage: bool
    last_synced_at: str | None = None
