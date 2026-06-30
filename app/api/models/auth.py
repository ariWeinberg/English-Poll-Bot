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
