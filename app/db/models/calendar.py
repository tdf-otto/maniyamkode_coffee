"""calendar_events — editable Wayanad Robusta phenology reference table."""
from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    phenostage: Mapped[str]               # e.g. 'blossom', 'monsoon'
    month_start: Mapped[int]              # 1-12 inclusive
    month_end: Mapped[int]                # 1-12 inclusive (may wrap, e.g. 12 -> 2)
    typical_activities: Mapped[str | None]
    notes: Mapped[str | None]
