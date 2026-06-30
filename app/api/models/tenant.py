from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WhatsAppConnectorPayload(BaseModel):
    provider: str = "greenapi"
    config: dict[str, Any] = Field(default_factory=dict)


class TenantPayload(BaseModel):
    name: str = "Tenant"
    username: str = ""
    password: str | None = None
    whatsapp_provider: str = "greenapi"
    whatsapp_connector: WhatsAppConnectorPayload | None = None
    greenapi_api_url: str = "https://api.green-api.com"
    greenapi_id_instance: str = ""
    greenapi_api_token_instance: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    timezone: str = "Asia/Jerusalem"
    poll_pool_target_size: int = Field(default=10, ge=1)
    poll_pool_refill_batch_size: int = Field(default=5, ge=1)
    poll_pool_refill_threshold_percent: int = Field(default=80, ge=0, le=100)
    poll_pool_threshold_percent: int = Field(default=80, ge=0, le=100)
    summary_enabled: bool = True
    scheduler_enabled: bool = True
    is_active: bool = True
