"""Week-of-year baselines per (plot, series), recomputed by scripts/analyze.py.

Every vegetation metric is presented primarily as its status versus the
plot's own history for the same week of the year (percentile and z-score),
not as an absolute number.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
from sqlalchemy import select

from ..db import SessionLocal, utcnow
from ..db.models import Baseline, ObservationSeries, PlotObservation


def iso_week(ts: str) -> int:
    return datetime.fromisoformat(ts).isocalendar().week


def recompute_baselines() -> int:
    """Recompute the baselines table from all valid plot_observations."""
    n_rows = 0
    with SessionLocal() as s:
        series = s.execute(select(ObservationSeries)).scalars().all()
        for ser in series:
            obs = s.execute(
                select(PlotObservation).where(
                    PlotObservation.series_id == ser.series_id,
                    PlotObservation.valid == 1,
                    PlotObservation.value.is_not(None),
                )
            ).scalars().all()
            by_plot: dict[int, list[tuple[int, float]]] = {}
            for o in obs:
                by_plot.setdefault(o.plot_id, []).append((iso_week(o.ts), float(o.value)))
            for plot_id, pairs in by_plot.items():
                by_week: dict[int, list[float]] = {}
                for wk, v in pairs:
                    by_week.setdefault(wk, []).append(v)
                for wk, vals in by_week.items():
                    a = np.array(vals, dtype=float)
                    row = s.get(Baseline, (ser.series_id, plot_id, wk))
                    if row is None:
                        row = Baseline(series_id=ser.series_id, plot_id=plot_id, week=wk)
                        s.add(row)
                    row.n = int(a.size)
                    row.median = float(np.median(a))
                    row.q25, row.q75 = (float(x) for x in np.percentile(a, [25, 75]))
                    row.mean = float(a.mean())
                    row.std = float(a.std(ddof=1)) if a.size > 1 else 0.0
                    row.mad = float(np.median(np.abs(a - np.median(a))))
                    row.p05, row.p95 = (float(x) for x in np.percentile(a, [5, 95]))
                    row.updated_at = utcnow()
                    n_rows += 1
        s.commit()
    return n_rows


def baseline_for(series_id: int, plot_id: int, week: int) -> dict | None:
    """Baseline row as a dict, falling back to nearest weeks if the exact
    week has too few samples (young history)."""
    with SessionLocal() as s:
        row = s.get(Baseline, (series_id, plot_id, week))
        if row and (row.n or 0) >= 2:
            return _as_dict(row)
        # fall back: pool weeks +-2
        rows = s.execute(
            select(Baseline).where(
                Baseline.series_id == series_id,
                Baseline.plot_id == plot_id,
                Baseline.week.between(max(1, week - 2), min(53, week + 2)),
            )
        ).scalars().all()
        if not rows:
            return None
        vals_n = sum(r.n or 0 for r in rows)
        if vals_n == 0:
            return None
        # weighted blend of the stored stats
        def wavg(attr):
            return sum((getattr(r, attr) or 0.0) * (r.n or 0) for r in rows) / vals_n
        return {
            "n": vals_n, "median": wavg("median"), "q25": wavg("q25"), "q75": wavg("q75"),
            "mean": wavg("mean"), "std": wavg("std"), "mad": wavg("mad"),
            "p05": wavg("p05"), "p95": wavg("p95"),
        }


def _as_dict(row: Baseline) -> dict:
    return {k: getattr(row, k) for k in
            ("n", "median", "q25", "q75", "mean", "std", "mad", "p05", "p95", "week")}


def _robust_scale(baseline: dict) -> tuple[float, float]:
    """Return (centre, scale) for z-scoring: median + 1.4826*MAD (robust to a
    single anomalous year), falling back to mean/std. Scale gets a floor of
    0.5% + 2% of |centre| so a young/tight history doesn't give absurd z."""
    centre = baseline.get("median")
    if centre is None:
        centre = baseline.get("mean")
    mad = baseline.get("mad")
    if mad is not None and mad > 1e-12:
        scale = 1.4826 * mad
    else:
        scale = baseline.get("std") or 0.0
    centre = centre or 0.0
    scale = max(scale, 0.005 + 0.02 * abs(centre))
    return centre, scale


def percentile_of(value: float, baseline: dict) -> float | None:
    """Approximate percentile of `value` within the baseline distribution."""
    if baseline.get("median") is None and baseline.get("mean") is None:
        return None
    centre, scale = _robust_scale(baseline)
    z = (value - centre) / scale
    from math import erf, sqrt

    return 50.0 * (1.0 + erf(z / sqrt(2.0)))


def zscore_of(value: float, baseline: dict) -> float | None:
    """Robust z-score vs the week-of-year baseline (median/MAD based)."""
    if baseline.get("median") is None and baseline.get("mean") is None:
        return None
    centre, scale = _robust_scale(baseline)
    return (value - centre) / scale
