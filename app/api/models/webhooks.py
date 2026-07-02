from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WebhookEvent(BaseModel):
    id: int
    tenant_id: int
    provider: str
    endpoint_path: str
    type_webhook: str | None = None
    message_type: str | None = None
    provider_message_id: str | None = None
    greenapi_message_id: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    poll_id: int | None = None
    decision_status: str | None = None
    decision_reason: str | None = None
    payload_json: str
    received_at: str
    processed_at: str | None = None
    retry_count: int = 0
    last_retry_at: str | None = None
    last_retry_error: str | None = None
    error: str | None = None


class WebhookEventPage(BaseModel):
    items: list[WebhookEvent]
    total: int
    page: int
    page_size: int
    has_next: bool
