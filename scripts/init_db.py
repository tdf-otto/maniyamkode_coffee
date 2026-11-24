#!/usr/bin/env python3
"""Apply numbered SQL migrations and register plots from the GeoJSON.

Usage:  python scripts/init_db.py
Safe to run repeatedly (idempotent).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import init_db  # noqa: E402
from app.services.geo import register_plots  # noqa: E402
from app.services.pipeline import register_default_sources  # noqa: E402


def main() -> None:
    applied = init_db()
    print(f"migrations applied: {applied or 'none (up to date)'}")
    summary = register_plots()
    print(f"plots registered: {summary['plots']} plots, {summary['boundaries']} boundaries")
    print(f"study bbox: {summary['bbox']}")
    register_default_sources()
    print("data source registry ready")


if __name__ == "__main__":
    main()
