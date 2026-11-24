"""management_events — unified record of everything done on a plot.

One table for harvest, applications, pest observations, field work, pruning
and composting. event_type picks the flavour; application rows additionally
carry input_class + pre_harvest_interval_days for the organic-conversion
checks (see app/services/organic.py).
"""
from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base

EVENT_TYPES = (
    "harvest",
    "application",
    "pest_observation",
    "field_work",
    "pruning",
    "composting",
)
INPUT_CLASSES = ("organic_allowed", "restricted", "prohibited")


class ManagementEvent(Base):
    __tablename__ = "management_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int]
    event_date: Mapped[str]               # ISO date
    season: Mapped[str | None]            # Indian coffee year '2024-25'
    event_type: Mapped[str]
    actor: Mapped[str | None]
    quantity: Mapped[float | None]
    unit: Mapped[str | None]
    product: Mapped[str | None]
    method: Mapped[str | None]
    input_class: Mapped[str | None]       # application rows only
    pre_harvest_interval_days: Mapped[int | None]  # application rows only
    meta_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str]
