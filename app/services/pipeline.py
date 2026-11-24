"""Shared ingestion helpers used by both the live (CDSE) and mock pipelines.

Everything funnels through here so zonal statistics land in
plot_observations exactly the same way regardless of where the raster came
from.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from .. import config
from ..db import SessionLocal, utcnow
from ..db.models import DataSource, ObservationSeries, Plot, PlotObservation, Scene
from . import raster as rio

# Registry of the variables the app knows how to present, with units.
KNOWN_SERIES = {
    ("ndvi", "s2"): "-",
    ("evi", "s2"): "-",
    ("ndre", "s2"): "-",
    ("ndre2", "s2"): "-",
    ("s1_vh", "s1"): "dB",
    ("s1_vv", "s1"): "dB",
    ("elevation_m", "dem"): "m",
    ("slope_deg", "dem"): "deg",
    ("canopy_height_m", "canopy"): "m",
    ("soil_moisture_10cm", "sensor"): "m3/m3",
}


def ensure_series(variable: str, source: str, unit: str | None = None) -> int:
    """Get or create an observation_series row; returns series_id."""
    unit = unit or KNOWN_SERIES.get((variable, source), "")
    with SessionLocal() as s:
        row = s.execute(
            select(ObservationSeries).where(
                ObservationSeries.variable == variable, ObservationSeries.source == source
            )
        ).scalar_one_or_none()
        if row is None:
            row = ObservationSeries(variable=variable, source=source, unit=unit)
            s.add(row)
            s.flush()
            sid = row.series_id
            s.commit()
            return sid
        return row.series_id


def write_plot_obs(series_id: int, plot_id: int, ts: str, value: float | None,
                   valid: bool = True) -> None:
    """Upsert one observation point."""
    with SessionLocal() as s:
        row = s.get(PlotObservation, (series_id, plot_id, ts))
        if row is None:
            row = PlotObservation(series_id=series_id, plot_id=plot_id, ts=ts,
                                  value=value, valid=int(valid))
            s.add(row)
        else:
            row.value = value
            row.valid = int(valid)
        s.commit()


def record_scene_observations(scene_id: str, source: str, date: str, cloud_pct: float | None,
                              cog_path: str, quicklook_path: str | None,
                              raster_path: Path, band_map: dict[str, int],
                              source_label: str) -> None:
    """Zonal-mean every mapped band of a scene COG per plot -> plot_observations.

    band_map: {variable: band_number} with band numbers matching the COG.
    Also upserts the scenes row.
    """
    series_ids = {var: ensure_series(var, source_label) for var in band_map}
    with SessionLocal() as s:
        plots = s.query(Plot).filter(Plot.is_boundary == 0).all()
        geoms = [(p.plot_id, p.geom_geojson) for p in plots]
        for var, band in band_map.items():
            for plot_id, gj in geoms:
                v = rio.zonal_mean(raster_path, gj, band)
                if v is not None:
                    row = s.get(PlotObservation, (series_ids[var], plot_id, date))
                    if row is None:
                        s.add(PlotObservation(series_id=series_ids[var], plot_id=plot_id,
                                              ts=date, value=v, valid=1))
                    else:
                        row.value = v
                        row.valid = 1
        existing = s.get(Scene, scene_id)
        if existing is None:
            s.add(Scene(scene_id=scene_id, source=source, date=date, cloud_pct=cloud_pct,
                        cog_path=cog_path, quicklook_path=quicklook_path,
                        meta_json=json.dumps({"band_map": band_map})))
        else:
            existing.cog_path = cog_path
            existing.quicklook_path = quicklook_path
            existing.cloud_pct = cloud_pct
        s.commit()


def touch_source(source_key: str, description: str, status: str = "ok") -> None:
    """Update the data_sources registry (freshness shown on the home strip)."""
    with SessionLocal() as s:
        row = s.get(DataSource, source_key)
        if row is None:
            row = DataSource(source_key=source_key)
            s.add(row)
        row.description = description
        row.last_run = utcnow()
        row.status = status
        s.commit()


def register_default_sources() -> None:
    defaults = {
        "s2": "Sentinel-2 L2A optical scenes (NDVI/EVI/NDRE) via CDSE",
        "s1": "Sentinel-1 GRD monthly backscatter (monsoon layer) via CDSE",
        "dem": "Copernicus GLO-30 DEM (elevation, slope, hillshade)",
        "canopy": "GEDI/Landsat global canopy height",
        "soil": "Soil lab results (manual import / hooks)",
        "weather": "Weather station feed (hook, not yet connected)",
        "sensors": "Soil-moisture sensors (hook, not yet connected)",
    }
    with SessionLocal() as s:
        for key, desc in defaults.items():
            if s.get(DataSource, key) is None:
                s.add(DataSource(source_key=key, description=desc, last_run=None,
                                 status="never_run"))
        s.commit()


def scene_exists(scene_id: str) -> bool:
    with SessionLocal() as s:
        return s.get(Scene, scene_id) is not None


def last_scene_date(source: str) -> str | None:
    with SessionLocal() as s:
        row = s.execute(
            select(Scene.date).where(Scene.source == source).order_by(Scene.date.desc()).limit(1)
        ).scalar_one_or_none()
        return row
