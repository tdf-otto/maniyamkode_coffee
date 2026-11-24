"""Indian coffee-year helpers.

The coffee year runs Oct 1 -> Sep 30. Season '2024-25' means 2024-10-01 to
2025-09-30. Used for the season selector and season-over-season overlays,
aligned by day-of-season.
"""
from __future__ import annotations

from datetime import date, datetime

from .. import config


def season_of(d: date | datetime) -> str:
    """'2024-25' for any date inside that coffee year."""
    if isinstance(d, str):
        d = datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        d = d.date()
    if (d.month, d.day) >= (config.COFFEE_YEAR_START_MONTH, config.COFFEE_YEAR_START_DAY):
        return f"{d.year}-{str(d.year + 1)[2:]}"
    return f"{d.year - 1}-{str(d.year)[2:]}"


def season_bounds(season: str) -> tuple[date, date]:
    """(start, end) dates of a coffee year like '2024-25'."""
    y0 = int(season.split("-")[0])
    return date(y0, config.COFFEE_YEAR_START_MONTH, config.COFFEE_YEAR_START_DAY), \
        date(y0 + 1, config.COFFEE_YEAR_START_MONTH, config.COFFEE_YEAR_START_DAY) - \
        __import__("datetime").timedelta(days=1)


def day_of_season(d: date | datetime) -> int:
    """1-based day within the coffee year (Oct 1 = day 1)."""
    if isinstance(d, str):
        d = datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        d = d.date()
    start = date(d.year if (d.month, d.day) >= (10, 1) else d.year - 1, 10, 1)
    return (d - start).days + 1


def current_season() -> str:
    return season_of(date.today())


def list_seasons(available: list[str]) -> list[str]:
    return sorted(set(available) | {current_season()}, reverse=True)


def current_phenostage(month: int | None = None) -> dict | None:
    """The calendar_events row active for `month` (default: this month)."""
    from ..db import SessionLocal
    from ..db.models import CalendarEvent

    month = month or date.today().month
    with SessionLocal() as s:
        for ev in s.query(CalendarEvent).all():
            if ev.month_start <= ev.month_end:
                active = ev.month_start <= month <= ev.month_end
            else:  # wraps year end, e.g. harvest 12-2
                active = month >= ev.month_start or month <= ev.month_end
            if active:
                return {"phenostage": ev.phenostage, "month_start": ev.month_start,
                        "month_end": ev.month_end,
                        "typical_activities": ev.typical_activities, "notes": ev.notes}
    return None
