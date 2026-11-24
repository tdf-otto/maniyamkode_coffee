"""Organic-conversion compliance checks for application records.

Each plot may carry conversion_organic_start_date. From that date until 3
years have passed (NPOP conversion period), applications with
input_class != 'organic_allowed' are flagged as non-conforming. The UI shows
a per-plot conversion status and blocks/flags those applications.
"""
from __future__ import annotations

from datetime import date, datetime

from ..db import SessionLocal
from ..db.models import ManagementEvent, Plot

CONVERSION_PERIOD_YEARS = 3


def conversion_status(plot_id: int, today: date | None = None) -> dict:
    """Per-plot conversion status for the Overview tab."""
    today = today or date.today()
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        if p is None:
            return {"plot_id": plot_id, "status": "unknown"}
        start = p.conversion_organic_start_date
        if not start:
            return {"plot_id": plot_id, "plot_name": p.plot_name,
                    "status": "not_in_conversion", "start": None,
                    "message": "Not in organic conversion — conventional practices allowed."}
        start_d = datetime.fromisoformat(start).date()
        end_d = date(start_d.year + CONVERSION_PERIOD_YEARS, start_d.month, start_d.day)
        if today >= end_d:
            return {"plot_id": plot_id, "plot_name": p.plot_name, "status": "certified_eligible",
                    "start": start, "end": end_d.isoformat(),
                    "message": f"Conversion period complete ({start} + {CONVERSION_PERIOD_YEARS}y)."}
        remaining = (end_d - today).days
        return {"plot_id": plot_id, "plot_name": p.plot_name, "status": "in_conversion",
                "start": start, "end": end_d.isoformat(), "days_remaining": remaining,
                "message": f"In conversion since {start}; {remaining} days remaining. "
                           "Only organic_allowed inputs permitted."}


def check_application(plot_id: int, input_class: str | None, event_date: str) -> dict:
    """Compliance verdict for one application row. Returns {ok, reason}."""
    with SessionLocal() as s:
        p = s.get(Plot, plot_id)
        start = p.conversion_organic_start_date if p else None
    if not start:
        return {"ok": True, "reason": "plot not in conversion"}
    start_d = datetime.fromisoformat(start).date()
    end_d = date(start_d.year + CONVERSION_PERIOD_YEARS, start_d.month, start_d.day)
    ev_d = datetime.fromisoformat(event_date).date()
    if not (start_d <= ev_d <= end_d):
        return {"ok": True, "reason": "outside conversion window"}
    if input_class == "organic_allowed":
        return {"ok": True, "reason": "organic-allowed input during conversion"}
    return {"ok": False,
            "reason": f"NON-CONFORMING: '{input_class}' input applied on {event_date} while plot "
                      f"is in organic conversion (until {end_d.isoformat()}). This must be recorded "
                      "and disclosed in the NPOP inspection pack."}


def non_conforming_applications(plot_id: int) -> list[ManagementEvent]:
    with SessionLocal() as s:
        rows = s.query(ManagementEvent).filter(
            ManagementEvent.plot_id == plot_id,
            ManagementEvent.event_type == "application",
        ).all()
        return [r for r in rows
                if not check_application(plot_id, r.input_class, r.event_date)["ok"]]
