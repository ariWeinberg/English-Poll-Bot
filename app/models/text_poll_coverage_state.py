from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db_runtime import Base


class TextPollCoverageState(Base):
    __tablename__ = "text_poll_coverage_state"

    text_id: Mapped[int] = mapped_column(ForeignKey("texts.id", ondelete="CASCADE"), primary_key=True)
    source_hash: Mapped[str] = mapped_column(Text)
    section_count: Mapped[int] = mapped_column(Integer)
    next_section_index: Mapped[int] = mapped_column(Integer)
    cycle: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[str] = mapped_column(Text)
