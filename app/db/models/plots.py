"""plots — one row per GeoJSON feature (plots + estate boundaries)."""
from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class Plot(Base):
    __tablename__ = "plots"

    plot_id: Mapped[int] = mapped_column(primary_key=True)
    plot_name: Mapped[str]
    estate: Mapped[str] = mapped_column(default="PUL")
    area_ha: Mapped[float | None] = mapped_column()          # UTM 43N (EPSG:32643)
    version: Mapped[int] = mapped_column(default=1)
    is_boundary: Mapped[int] = mapped_column(default=0)      # 1 = estate boundary, not a plot
    centroid_lon: Mapped[float | None]
    centroid_lat: Mapped[float | None]
    geom_geojson: Mapped[str] = mapped_column(Text)          # WGS84 polygon
    conversion_organic_start_date: Mapped[str | None]       # ISO date or None
    created_at: Mapped[str]
    updated_at: Mapped[str]
