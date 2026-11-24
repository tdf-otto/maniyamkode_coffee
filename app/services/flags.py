"""Flagging rules (build prompt section 6). Recomputed by scripts/analyze.py.

Rules (thresholds in app/config.py):
  low_vs_history   : current z <= FLAG_ZSCORE or below FLAG_PCTL of the same
                     week in past years -> "canopy below historical range"
  sustained_ndre   : NDRE drop > FLAG_SUSTAINED_PCTL_DROP over 2 consecutive
                     acquisitions -> early-stress flag on NDRE specifically
  nutrient_stress  : NDVI stable but NDRE negative anomaly -> possible nutrient
                     stress (structure vs chemistry disentangled)
  monsoon_s1       : Jun-Sep anomaly logic applied to s1_vh

Each flag carries a plain-English `message` — the UI shows this sentence,
with the raw index on hover.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from .. import config
from ..db import SessionLocal, utcnow
from ..db.models import Flag, ObservationSeries, Plot, PlotObservation
from .baselines import baseline_for, iso_week, percentile_of, zscore_of

SEVERITY_ORDER = {"red": 3, "amber": 2, "info": 1}


def _latest_obs(series_id: int) -> dict[int, PlotObservation]:
    """Latest valid observation per plot for a series."""
    with SessionLocal() as s:
        rows = s.execute(
            select(PlotObservation)
            .where(PlotObservation.series_id == series_id, PlotObservation.valid == 1)
            .order_by(PlotObservation.ts.desc())
        ).scalars().all()
        out: dict[int, PlotObservation] = {}
        for r in rows:
            out.setdefault(r.plot_id, r)
        return out


def _series_history(series_id: int, plot_id: int, limit: int = 8) -> list[PlotObservation]:
    with SessionLocal() as s:
        rows = s.execute(
            select(PlotObservation)
            .where(PlotObservation.series_id == series_id,
                   PlotObservation.plot_id == plot_id,
                   PlotObservation.valid == 1)
            .order_by(PlotObservation.ts.desc())
            .limit(limit)
        ).scalars().all()
        return list(reversed(rows))


def _plot_name(plot_id: int) -> str:
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        return p.plot_name if p else f"plot {plot_id}"


def _series_var(series_id: int) -> str:
    with SessionLocal() as s:
        r = s.get(ObservationSeries, series_id)
        return r.variable if r else "?"


def recompute_flags() -> int:
    """Delete and regenerate all flags. Returns flag count."""
    with SessionLocal() as s:
        s.execute(Flag.__table__.delete())
        s.commit()
    n = 0
    with SessionLocal() as s:
        series = {r.variable: r.series_id for r in s.execute(select(ObservationSeries)).scalars()}
        plots = s.execute(select(Plot).where(Plot.is_boundary == 0)).scalars().all()
        now_month = datetime.now().month
        monsoon = now_month in config.FLAG_S1_MONSOON_MONTHS

        for var, sid in series.items():
            latest = _latest_obs(sid)
            for plot in plots:
                obs = latest.get(plot.plot_id)
                if obs is None or obs.value is None:
                    continue
                wk = iso_week(obs.ts)
                base = baseline_for(sid, plot.plot_id, wk)
                if not base:
                    continue
                pctl = percentile_of(obs.value, base)
                z = zscore_of(obs.value, base)
                low = (z is not None and z <= config.FLAG_ZSCORE) or \
                      (pctl is not None and pctl <= config.FLAG_PCTL)
                # monsoon: only s1_vh is evaluated for anomaly during Jun-Sep
                if var == "s1_vh" and not monsoon:
                    continue
                if var != "s1_vh" and monsoon and var in ("ndvi", "evi", "ndre", "ndre2"):
                    continue  # optical unreliable in monsoon; S1 carries the signal
                if low:
                    sev = "red" if (z is not None and z <= config.FLAG_ZSCORE - 1) or \
                          (pctl is not None and pctl <= 1) else "amber"
                    msg = (f"{_plot_name(plot.plot_id)} {var} is below its historical range for "
                           f"week {wk} (z={z:.1f}, pctl={pctl:.0f}%).")
                    s.add(Flag(plot_id=plot.plot_id, series_id=sid, scene_date=obs.ts,
                               rule="low_vs_history", severity=sev,
                               pctl=pctl, z=z, message=msg, created_at=utcnow()))
                    n += 1

        # sustained NDRE drop over 2 consecutive acquisitions
        ndre_sid = series.get("ndre")
        ndvi_sid = series.get("ndvi")
        if ndre_sid:
            for plot in plots:
                hist = _series_history(ndre_sid, plot.plot_id, limit=3)
                if len(hist) >= 3 and hist[-1].value is not None and hist[-2].value is not None \
                        and hist[-3].value is not None:
                    # compare each point against ITS OWN week-of-year baseline (z-scores),
                    # so the drop is baseline-relative, not raw
                    zs = []
                    for h in hist[-3:]:
                        b = baseline_for(ndre_sid, plot.plot_id, iso_week(h.ts))
                        zs.append(zscore_of(h.value, b) if b and h.value is not None else None)
                    p_now = None
                    b_now = baseline_for(ndre_sid, plot.plot_id, iso_week(hist[-1].ts))
                    if b_now:
                        p_now = percentile_of(hist[-1].value, b_now)
                    if zs[-1] is not None and zs[-2] is not None and zs[-1] <= -1.5 and \
                            (zs[-2] - zs[-1]) >= 1.0:
                        s.add(Flag(plot_id=plot.plot_id, series_id=ndre_sid,
                                   scene_date=hist[-1].ts, rule="sustained_ndre",
                                   severity="amber", pctl=p_now, z=zs[-1],
                                   message=(f"{_plot_name(plot.plot_id)} NDRE is running low versus "
                                            f"the same week in past years (z={zs[-1]:.1f}) and dropped "
                                            f"further over the last two acquisitions — early stress "
                                            "signal."),
                                   created_at=utcnow()))
                        n += 1
                        # NDVI stable but NDRE negative -> nutrient stress
                        if ndvi_sid and p_now < 25:
                            nh = _series_history(ndvi_sid, plot.plot_id, limit=2)
                            if len(nh) >= 2 and nh[-1].value is not None:
                                nbase = baseline_for(ndvi_sid, plot.plot_id, iso_week(nh[-1].ts))
                                if nbase:
                                    nz = zscore_of(nh[-1].value, nbase)
                                    if nz is not None and nz > -1.0:
                                        s.add(Flag(plot_id=plot.plot_id, series_id=ndre_sid,
                                                   scene_date=hist[-1].ts, rule="nutrient_stress",
                                                   severity="amber", pctl=p_now, z=None,
                                                   message=(f"{_plot_name(plot.plot_id)}: canopy structure "
                                                            "(NDVI) is normal but NDRE is low — possible "
                                                            "nutrient/chlorophyll stress."),
                                                   created_at=utcnow()))
                                        n += 1
        s.commit()
    return n


def current_flags(limit: int = 50) -> list[dict]:
    """All flags, worst severity first, as plain dicts for the API."""
    with SessionLocal() as s:
        rows = s.execute(select(Flag)).scalars().all()
        out = []
        for f in rows:
            p = s.get(Plot, f.plot_id)
            ser = s.get(ObservationSeries, f.series_id) if f.series_id else None
            out.append({
                "flag_id": f.flag_id, "plot_id": f.plot_id,
                "plot_name": p.plot_name if p else "?",
                "area_ha": p.area_ha if p else None,
                "centroid": [p.centroid_lon, p.centroid_lat] if p else None,
                "variable": ser.variable if ser else None,
                "source": ser.source if ser else None,
                "rule": f.rule, "severity": f.severity,
                "pctl": f.pctl, "z": f.z, "scene_date": f.scene_date,
                "message": f.message,
            })
        out.sort(key=lambda r: (SEVERITY_ORDER.get(r["severity"], 0), r["pctl"] or 100), reverse=True)
        return out[:limit]
