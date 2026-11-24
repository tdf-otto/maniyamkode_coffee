#!/usr/bin/env python3
"""Incremental update: fetch scenes since the last run, recompute baselines
and flags. Designed to be cron'd on the mini-PC later.

Usage:
  python scripts/update.py            # live
  python scripts/update.py --mock     # regenerate the most recent mock month only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services.pipeline import last_scene_date, touch_source  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    config.ensure_dirs()
    from scripts.analyze import run_analysis

    if args.mock or config.APP_MODE == "mock":
        # mock mode: regenerate just the current month so update feels live
        from app.services import mockdata
        from app.services.geo import derive_bbox, load_geojson
        from datetime import date

        bbox = derive_bbox(load_geojson())
        d = date.today().replace(day=15)
        # reuse the generator for a single month by calling with months=1
        # (idempotent upserts keep history intact)
        mockdata.generate_s2_mock(bbox, 1, config.PROCESSED_DIR)
        mockdata.generate_s1_mock(bbox, 1, config.PROCESSED_DIR)
        touch_source("s2", "Sentinel-2 L2A (mock)", "ok")
        touch_source("s1", "Sentinel-1 GRD monthly (mock)", "ok")
    else:
        from app.services.geo import derive_bbox, load_geojson
        from app.services import cdse

        if not cdse.have_credentials():
            raise SystemExit("live update needs CDSE credentials in .env (or use --mock)")
        bbox = derive_bbox(load_geojson())
        last = last_scene_date("s2") or "2000-01-01"
        print(f"[update] fetching S2 scenes since {last}")
        # delegate to preload's live path; it skips scenes already cached
        from scripts.preload import run_live

        run_live(months=1)

    run_analysis()
    print("update complete")


if __name__ == "__main__":
    main()
