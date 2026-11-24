"""Offline breakpoint detection: a simple CUSUM scan per plot per series.

Produces "disturbance suspected around <date>" entries for the plot timeline.
Full BFAST is optional later; CUSUM catches the step changes that matter for
interventions (pruning, clearing, pest outbreaks).
"""
from __future__ import annotations

import numpy as np
from sqlalchemy import select

from ..db import SessionLocal, utcnow
from ..db.models import Breakpoint, ObservationSeries, PlotObservation


def cusum_breaks(ts: list[str], values: list[float], min_magnitude: float = 0.8) -> list[tuple[str, float]]:
    """Standard CUSUM change-point scan on a regular-ish series.

    Returns [(break_date, standardized_magnitude)] for detected steps.
    """
    if len(values) < 6:
        return []
    a = np.asarray(values, dtype=float)
    if not np.isfinite(a).all():
        return []
    mean, std = a.mean(), a.std(ddof=1)
    if std < 1e-12:
        return []
    z = (a - mean) / std
    cusum = np.cumsum(z)
    # two-sided: max deviation of cumulative sum from its endpoints line
    n = len(z)
    line = np.linspace(cusum[0], cusum[-1], n)
    dev = cusum - line
    i = int(np.argmax(np.abs(dev)))
    magnitude = float(abs(dev[i]) / np.sqrt(n))
    if magnitude < min_magnitude:
        return []
    return [(ts[i], magnitude)]


def recompute_breakpoints() -> int:
    """Recompute breakpoints table. Returns count."""
    n = 0
    with SessionLocal() as s:
        s.execute(Breakpoint.__table__.delete())
        series = s.execute(select(ObservationSeries)).scalars().all()
        for ser in series:
            obs = s.execute(
                select(PlotObservation)
                .where(PlotObservation.series_id == ser.series_id, PlotObservation.valid == 1,
                       PlotObservation.value.is_not(None))
                .order_by(PlotObservation.plot_id, PlotObservation.ts)
            ).scalars().all()
            by_plot: dict[int, list[PlotObservation]] = {}
            for o in obs:
                by_plot.setdefault(o.plot_id, []).append(o)
            for plot_id, rows in by_plot.items():
                ts = [r.ts for r in rows]
                vals = [float(r.value) for r in rows]
                for date_str, mag in cusum_breaks(ts, vals):
                    s.add(Breakpoint(plot_id=plot_id, series_id=ser.series_id,
                                     break_date=date_str[:10], magnitude=mag, method="cusum"))
                    n += 1
        s.commit()
    return n
