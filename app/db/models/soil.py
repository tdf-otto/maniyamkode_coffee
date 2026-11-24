"""soil_samples + tree_census — long-format tables the ingest hooks write to."""
from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SoilSample(Base):
    __tablename__ = "soil_samples"

    sample_id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int]
    sample_date: Mapped[str]       # ISO date
    depth_cm: Mapped[float | None]
    parameter: Mapped[str]         # pH, organic_carbon_pct, N_kg_ha, ...
    value: Mapped[float | None]
    unit: Mapped[str | None]
    lab: Mapped[str | None]
    method: Mapped[str | None]


class TreeCensus(Base):
    __tablename__ = "tree_census"

    census_id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int]
    census_date: Mapped[str]       # ISO date
    tree_count: Mapped[int | None]
    coffee_shade_split: Mapped[str | None] = mapped_column(Text)  # JSON
    source: Mapped[str | None]     # map | drone | manual
    meta_json: Mapped[str | None] = mapped_column(Text)
