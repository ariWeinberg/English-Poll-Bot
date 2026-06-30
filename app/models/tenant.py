from __future__ import annotations

from sqlalchemy import Boolean, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db_runtime import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    username: Mapped[str] = mapped_column(Text)
    password: Mapped[str] = mapped_column(Text)
    gemini_api_key: Mapped[str] = mapped_column(Text)
    gemini_model: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)
    poll_pool_target_size: Mapped[int] = mapped_column(Integer)
    poll_pool_refill_batch_size: Mapped[int] = mapped_column(Integer)
    poll_pool_refill_threshold_percent: Mapped[int] = mapped_column(Integer)
    poll_pool_threshold_percent: Mapped[int] = mapped_column(Integer)
    summary_enabled: Mapped[bool] = mapped_column(Boolean)
    scheduler_enabled: Mapped[bool] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean)
