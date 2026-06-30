from __future__ import annotations

from pydantic import BaseModel, model_validator


class ChatPolicyPayload(BaseModel):
    policy: str

    @model_validator(mode="after")
    def validate_policy(self) -> "ChatPolicyPayload":
        if self.policy not in {"allow", "neutral", "block"}:
            raise ValueError("policy must be allow, neutral, or block")
        return self
