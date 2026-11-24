"""observation_series + plot_observations + scenes + baselines + flags + breakpoints.

The generic observation container: any zonal statistic or sensor reading is a
(series_id, plot_id, ts, value, valid) row. Baselines/flags/breakpoints are
derived tables recomputed by scripts/analyze.py.
"""
from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class ObservationSeries(Base):
    __tablename__ = "observation_series"

    series_id: Mapped[int] = mapped_column(primary_key=True)
    variable: Mapped[str]      # evi, ndvi, ndre, ndre2, ireci, s1_vh, s1_vv, soil_moisture_10cm, ...
    source: Mapped[str]        # s2, s1, sensor, manual, dem, canopy
    unit: Mapped[str | None]

    __table_args__ = ({"sqlite_autoincrement": True},)


class PlotObservation(Base):
    __tablename__ = "plot_observations"

    series_id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[str] = mapped_column(primary_key=True)   # ISO 8601
    value: Mapped[float | None]
    valid: Mapped[int] = mapped_column(default=1)


class Scene(Base):
    __tablename__ = "scenes"

    scene_id: Mapped[str] = mapped_column(primary_key=True)
    source: Mapped[str]            # s2 | s1 | dem | canopy
    date: Mapped[str]              # ISO date
    cloud_pct: Mapped[float | None]
    cog_path: Mapped[str | None] = mapped_column(Text)
    quicklook_path: Mapped[str | None] = mapped_column(Text)
    meta_json: Mapped[str | None] = mapped_column(Text)


class Baseline(Base):
    __tablename__ = "baselines"

    series_id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int] = mapped_column(primary_key=True)
    week: Mapped[int] = mapped_column(primary_key=True)   # ISO week 1-53
    n: Mapped[int | None]
    median: Mapped[float | None]
    q25: Mapped[float | None]
    q75: Mapped[float | None]
    mean: Mapped[float | None]
    std: Mapped[float | None]
    mad: Mapped[float | None]
    p05: Mapped[float | None]
    p95: Mapped[float | None]
    updated_at: Mapped[str]


class Flag(Base):
    __tablename__ = "flags"

    flag_id: Mapped[int] = mapped_column(primary_key=True)
    plot_id: Mapped[int]
    series_id: Mapped[int | None]
    scene_date: Mapped[str | None]
    rule: Mapped[str]
    severity: Mapped[str]          # info | amber | red
    pctl: Mapped[float | None]
    z: Mapped[float | None]
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str]


class Breakpoint(Base):
    __tablename__ = "breakpoints"

    plot_id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(primary_key=True)
    break_date: Mapped[str] = mapped_column(primary_key=True)
    magnitude: Mapped[float | None]
    method: Mapped[str] = mapped_column(default="cusum")
