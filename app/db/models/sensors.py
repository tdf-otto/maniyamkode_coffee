"""sensor_devices + data_sources registry."""
from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class SensorDevice(Base):
    __tablename__ = "sensor_devices"

    device_id: Mapped[str] = mapped_column(primary_key=True)
    plot_id: Mapped[int | None]    # NULL = estate-level device (weather station)
    variable: Mapped[str]
    unit: Mapped[str | None]
    location_wkt: Mapped[str | None]


class DataSource(Base):
    __tablename__ = "data_sources"

    source_key: Mapped[str] = mapped_column(primary_key=True)  # s2, s1, dem, canopy, soil, weather
    description: Mapped[str | None]
    last_run: Mapped[str | None]   # ISO timestamp
    status: Mapped[str | None]     # ok | stale | error | never_run
