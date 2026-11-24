"""REST API for the farm monitoring app.

All endpoints are read-mostly; writes go through /api/records (management
events) and the plot conversion setter. The frontend is plain JS calling
these endpoints — no build step.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from . import config
from .db import SessionLocal, utcnow
from .db.models import (
    Baseline,
    Breakpoint,
    CalendarEvent,
    Flag,
    ManagementEvent,
    ObservationSeries,
    Plot,
    PlotObservation,
    Scene,
    SoilSample,
    TreeCensus,
    DataSource,
)
from .services.baselines import baseline_for, iso_week, percentile_of, zscore_of
from .services.export import export_all_zip
from .services.flags import current_flags
from .services.geo import geojson_response
from .services.inspection import build_inspection_pack
from .services.organic import check_application, conversion_status
from .services.season import current_phenostage, current_season, day_of_season, season_of

router = APIRouter(prefix="/api")


# --- home / attention --------------------------------------------------------

@router.get("/home")
def home():
    """Everything the home screen needs in one call."""
    return {
        "estate": "Maniyamkode (PUL), Wayanad, Kerala",
        "phenostage": current_phenostage(),
        "monsoon": date.today().month in config.FLAG_S1_MONSOON_MONTHS,
        "monsoon_months": list(config.FLAG_S1_MONSOON_MONTHS),
        "current_season": current_season(),
        "sources": _sources(),
        "flags": current_flags(limit=50),
    }


def _sources() -> list[dict]:
    with SessionLocal() as s:
        return [
            {"source_key": r.source_key, "description": r.description,
             "last_run": r.last_run, "status": r.status}
            for r in s.execute(select(DataSource).order_by(DataSource.source_key)).scalars()
        ]


# --- plots -------------------------------------------------------------------

@router.get("/plots")
def plots(include_boundaries: bool = False):
    """Plot list + GeoJSON in one payload."""
    gj = geojson_response(include_boundaries=include_boundaries)
    with SessionLocal() as s:
        rows = s.execute(
            select(Plot).where(Plot.is_boundary == 0).order_by(Plot.plot_name)
        ).scalars().all()
        plot_list = [
            {"plot_id": p.plot_id, "plot_name": p.plot_name, "area_ha": p.area_ha,
             "centroid": [p.centroid_lon, p.centroid_lat],
             "conversion_organic_start_date": p.conversion_organic_start_date}
            for p in rows
        ]
    return {"geojson": gj, "plots": plot_list, "bbox": _bbox()}


def _bbox() -> dict:
    from .services.geo import derive_bbox, load_geojson

    return derive_bbox(load_geojson())


@router.get("/plots/{plot_id}")
def plot_overview(plot_id: int):
    """Overview tab payload: identity, terrain, canopy, conversion, chips."""
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        if p is None:
            raise HTTPException(404, "plot not found")
        series = s.execute(select(ObservationSeries)).scalars().all()
        chips = []
        for ser in series:
            obs = s.execute(
                select(PlotObservation)
                .where(PlotObservation.series_id == ser.series_id,
                       PlotObservation.plot_id == plot_id, PlotObservation.valid == 1)
                .order_by(PlotObservation.ts.desc()).limit(1)
            ).scalar_one_or_none()
            if obs is None or obs.value is None:
                continue
            base = baseline_for(ser.series_id, plot_id, iso_week(obs.ts))
            pctl = percentile_of(obs.value, base) if base else None
            z = zscore_of(obs.value, base) if base else None
            status = "green"
            if pctl is not None and pctl <= 5:
                status = "red"
            elif pctl is not None and pctl <= 25:
                status = "amber"
            chips.append({"variable": ser.variable, "source": ser.source, "unit": ser.unit,
                          "value": round(obs.value, 4), "ts": obs.ts, "pctl": pctl and round(pctl, 1),
                          "z": z and round(z, 2), "status": status})
        return {
            "plot_id": p.plot_id, "plot_name": p.plot_name, "estate": p.estate,
            "area_ha": p.area_ha, "version": p.version,
            "centroid": [p.centroid_lon, p.centroid_lat],
            "conversion": conversion_status(plot_id),
            "chips": chips,
            "geojson": {"type": "Feature", "properties": {"plot_id": p.plot_id},
                        "geometry": json.loads(p.geom_geojson)},
        }


class ConversionIn(BaseModel):
    start_date: str | None  # ISO date or null to clear


@router.put("/plots/{plot_id}/conversion")
def set_conversion(plot_id: int, body: ConversionIn):
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        if p is None:
            raise HTTPException(404, "plot not found")
        p.conversion_organic_start_date = body.start_date
        p.updated_at = utcnow()
        s.commit()
        return conversion_status(plot_id)


# --- observations / series ---------------------------------------------------

@router.get("/series")
def series_list():
    with SessionLocal() as s:
        rows = s.execute(select(ObservationSeries).order_by(ObservationSeries.variable)).scalars()
        return [{"series_id": r.series_id, "variable": r.variable, "source": r.source,
                 "unit": r.unit} for r in rows]


@router.get("/observations")
def observations(plot_id: int, series: str = Query(..., description="variable name, e.g. ndre"),
                 source: str = "s2", frm: str | None = None, to: str | None = None):
    """Time series for one plot+variable, with per-point baseline stats."""
    with SessionLocal() as s:
        ser = s.execute(
            select(ObservationSeries).where(ObservationSeries.variable == series,
                                            ObservationSeries.source == source)
        ).scalar_one_or_none()
        if ser is None:
            raise HTTPException(404, f"no series {series}/{source}")
        q = select(PlotObservation).where(PlotObservation.series_id == ser.series_id,
                                          PlotObservation.plot_id == plot_id,
                                          PlotObservation.valid == 1)
        if frm:
            q = q.where(PlotObservation.ts >= frm)
        if to:
            q = q.where(PlotObservation.ts <= to + "T23:59:59")
        rows = s.execute(q.order_by(PlotObservation.ts)).scalars().all()
        out = []
        for r in rows:
            base = baseline_for(ser.series_id, plot_id, iso_week(r.ts))
            pctl = percentile_of(r.value, base) if base and r.value is not None else None
            z = zscore_of(r.value, base) if base and r.value is not None else None
            out.append({"ts": r.ts, "value": r.value, "week": iso_week(r.ts),
                        "pctl": pctl and round(pctl, 1), "z": z and round(z, 2),
                        "median": base and base.get("median"), "q25": base and base.get("q25"),
                        "q75": base and base.get("q75"), "p05": base and base.get("p05"),
                        "p95": base and base.get("p95"),
                        "day_of_season": day_of_season(r.ts[:10]),
                        "season": season_of(r.ts[:10])})
        return {"series": series, "source": source, "plot_id": plot_id, "points": out}


@router.get("/flags")
def flags():
    return {"flags": current_flags(limit=100)}


@router.get("/maplayer")
def maplayer(variable: str, source: str = "s2", date: str | None = None):
    """Per-plot status of one variable at (or just before) `date` — the map's
    traffic-light colouring. Static variables (elevation, canopy, area) ignore date."""
    with SessionLocal() as s:
        ser = s.execute(
            select(ObservationSeries).where(ObservationSeries.variable == variable,
                                            ObservationSeries.source == source)
        ).scalar_one_or_none()
        plots = s.execute(select(Plot).where(Plot.is_boundary == 0)).scalars().all()
        if ser is None:
            # static layer from plots table (area)
            return {"variable": variable, "points": [
                {"plot_id": p.plot_id, "value": p.area_ha, "pctl": None, "z": None,
                 "status": "green", "ts": None} for p in plots]}
        out = []
        for p in plots:
            q = select(PlotObservation).where(PlotObservation.series_id == ser.series_id,
                                              PlotObservation.plot_id == p.plot_id,
                                              PlotObservation.valid == 1)
            if date:
                q = q.where(PlotObservation.ts <= date + "T23:59:59")
            obs = s.execute(q.order_by(PlotObservation.ts.desc()).limit(1)).scalar_one_or_none()
            if obs is None or obs.value is None:
                continue
            base = baseline_for(ser.series_id, p.plot_id, iso_week(obs.ts))
            pctl = percentile_of(obs.value, base) if base else None
            z = zscore_of(obs.value, base) if base else None
            status = "green"
            if pctl is not None and pctl <= 5:
                status = "red"
            elif pctl is not None and pctl <= 25:
                status = "amber"
            out.append({"plot_id": p.plot_id, "value": round(obs.value, 4), "pctl": pctl and round(pctl, 1),
                        "z": z and round(z, 2), "status": status, "ts": obs.ts})
        return {"variable": variable, "source": source, "date": date, "points": out}


@router.get("/scenes")
def scenes(source: str | None = None):
    with SessionLocal() as s:
        q = select(Scene).order_by(Scene.date.desc())
        if source:
            q = q.where(Scene.source == source)
        rows = s.execute(q).scalars().all()
        return {"scenes": [
            {"scene_id": r.scene_id, "source": r.source, "date": r.date,
             "cloud_pct": r.cloud_pct, "cog_path": r.cog_path, "quicklook_path": r.quicklook_path,
             "meta": json.loads(r.meta_json) if r.meta_json else {}}
            for r in rows]}


# --- plot detail: season, records, soil, imagery -----------------------------

@router.get("/plots/{plot_id}/season")
def plot_season(plot_id: int, season: str | None = None):
    """Season-over-season overlay data: all optical series aligned by day-of-season."""
    season = season or current_season()
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        if p is None:
            raise HTTPException(404, "plot not found")
        out = {"plot_id": plot_id, "plot_name": p.plot_name, "season": season,
               "series": {}, "breakpoints": [], "events": []}
        for ser in s.execute(select(ObservationSeries).where(
                ObservationSeries.source.in_(["s2", "s1"]))).scalars():
            rows = s.execute(
                select(PlotObservation).where(PlotObservation.series_id == ser.series_id,
                                              PlotObservation.plot_id == plot_id,
                                              PlotObservation.valid == 1)
                .order_by(PlotObservation.ts)).scalars().all()
            out["series"][f"{ser.variable}"] = [
                {"ts": r.ts, "value": r.value, "season": season_of(r.ts[:10]),
                 "day_of_season": day_of_season(r.ts[:10])} for r in rows]
        out["breakpoints"] = [
            {"break_date": b.break_date, "magnitude": b.magnitude, "method": b.method,
             "variable": s.get(ObservationSeries, b.series_id).variable}
            for b in s.execute(select(Breakpoint).where(Breakpoint.plot_id == plot_id)).scalars()]
        out["events"] = [
            {"date": e.event_date, "type": e.event_type, "product": e.product,
             "input_class": e.input_class, "quantity": e.quantity, "unit": e.unit,
             "actor": e.actor, "season": e.season}
            for e in s.execute(select(ManagementEvent).where(ManagementEvent.plot_id == plot_id)
                               .order_by(ManagementEvent.event_date)).scalars()]
        return out


@router.get("/plots/{plot_id}/soil")
def plot_soil(plot_id: int):
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        if p is None:
            raise HTTPException(404, "plot not found")
        samples = s.execute(select(SoilSample).where(SoilSample.plot_id == plot_id)
                            .order_by(SoilSample.sample_date, SoilSample.parameter)).scalars().all()
        census = s.execute(select(TreeCensus).where(TreeCensus.plot_id == plot_id)
                           .order_by(TreeCensus.census_date.desc())).scalars().all()
        params: dict[str, list] = {}
        for r in samples:
            params.setdefault(r.parameter, []).append(
                {"sample_date": r.sample_date, "value": r.value, "unit": r.unit,
                 "depth_cm": r.depth_cm, "lab": r.lab, "method": r.method})
        return {"plot_id": plot_id, "plot_name": p.plot_name,
                "soil": params,
                "census": [{"census_date": c.census_date, "tree_count": c.tree_count,
                            "coffee_shade_split": c.coffee_shade_split, "source": c.source}
                           for c in census]}


# --- records CRUD ------------------------------------------------------------

class RecordIn(BaseModel):
    event_date: str
    event_type: str
    actor: str | None = None
    quantity: float | None = None
    unit: str | None = None
    product: str | None = None
    method: str | None = None
    input_class: str | None = None
    pre_harvest_interval_days: int | None = None
    meta_json: dict | None = None


@router.get("/plots/{plot_id}/records")
def list_records(plot_id: int):
    with SessionLocal() as s:
        rows = s.execute(select(ManagementEvent).where(ManagementEvent.plot_id == plot_id)
                         .order_by(ManagementEvent.event_date.desc())).scalars().all()
        return {"records": [_record_dict(r, plot_id) for r in rows]}


def _record_dict(r: ManagementEvent, plot_id: int) -> dict:
    verdict = None
    if r.event_type == "application":
        verdict = check_application(plot_id, r.input_class, r.event_date)
    return {"id": r.id, "plot_id": r.plot_id, "event_date": r.event_date, "season": r.season,
            "event_type": r.event_type, "actor": r.actor, "quantity": r.quantity, "unit": r.unit,
            "product": r.product, "method": r.method, "input_class": r.input_class,
            "pre_harvest_interval_days": r.pre_harvest_interval_days,
            "meta": json.loads(r.meta_json) if r.meta_json else {},
            "compliance": verdict}


@router.post("/plots/{plot_id}/records", status_code=201)
def create_record(plot_id: int, body: RecordIn):
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        if p is None:
            raise HTTPException(404, "plot not found")
        if body.event_type not in ("harvest", "application", "pest_observation",
                                   "field_work", "pruning", "composting"):
            raise HTTPException(422, "unknown event_type")
        ev = ManagementEvent(
            plot_id=plot_id, event_date=body.event_date,
            season=season_of(body.event_date), event_type=body.event_type,
            actor=body.actor, quantity=body.quantity, unit=body.unit,
            product=body.product, method=body.method, input_class=body.input_class,
            pre_harvest_interval_days=body.pre_harvest_interval_days,
            meta_json=json.dumps(body.meta_json) if body.meta_json else None,
            created_at=utcnow())
        s.add(ev)
        s.commit()
        s.refresh(ev)
        return _record_dict(ev, plot_id)


@router.delete("/records/{record_id}")
def delete_record(record_id: int):
    with SessionLocal() as s:
        r = s.get(ManagementEvent, record_id)
        if r is None:
            raise HTTPException(404, "record not found")
        plot_id = r.plot_id
        s.delete(r)
        s.commit()
        return {"deleted": record_id, "plot_id": plot_id}


@router.post("/plots/{plot_id}/inspection-pack")
def inspection_pack(plot_id: int, season: str | None = None):
    csv_path, pdf_path = build_inspection_pack(plot_id, season)
    return {"csv": str(csv_path), "pdf": str(pdf_path),
            "csv_url": f"/api/download?path={csv_path}",
            "pdf_url": f"/api/download?path={pdf_path}"}


# --- misc --------------------------------------------------------------------

@router.get("/calendar")
def calendar():
    with SessionLocal() as s:
        rows = s.execute(select(CalendarEvent).order_by(CalendarEvent.month_start)).scalars()
        return {"events": [{"phenostage": r.phenostage, "month_start": r.month_start,
                            "month_end": r.month_end,
                            "typical_activities": r.typical_activities, "notes": r.notes}
                           for r in rows],
                "current": current_phenostage()}


@router.get("/export")
def export_zip():
    path = export_all_zip()
    return FileResponse(path, media_type="application/zip",
                        filename=Path(path).name)


@router.get("/download")
def download(path: str):
    """Serve files from within the repo (exports, processed rasters)."""
    p = Path(path).resolve()
    if not str(p).startswith(str(config.ROOT.resolve())):
        raise HTTPException(403, "outside repo root")
    if not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p)
