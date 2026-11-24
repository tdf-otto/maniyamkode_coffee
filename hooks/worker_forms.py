#!/usr/bin/env python3
"""Hook: worker-submitted form records (CSV export from phones) -> management_events.

CSV columns: plot_name, event_date, event_type, actor, quantity, unit, product,
method, input_class, pre_harvest_interval_days, notes

Applications get the organic-conversion compliance check automatically on read
(see app/services/organic.py); non-conforming rows are highlighted in the UI
and listed in the inspection pack.

Usage:  python hooks/worker_forms.py --csv submissions.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, utcnow  # noqa: E402
from app.db.models import ManagementEvent, Plot  # noqa: E402
from app.services.pipeline import touch_source  # noqa: E402
from app.services.season import season_of  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()
    n = 0
    with SessionLocal() as s, open(args.csv) as fh:
        names = {p.plot_name: p.plot_id for p in s.query(Plot).all()}
        for row in csv.DictReader(fh):
            pid = names.get(row["plot_name"])
            if pid is None:
                print(f"skip unknown plot {row['plot_name']}")
                continue
            s.add(ManagementEvent(
                plot_id=pid, event_date=row["event_date"], season=season_of(row["event_date"]),
                event_type=row["event_type"], actor=row.get("actor") or None,
                quantity=float(row["quantity"]) if row.get("quantity") else None,
                unit=row.get("unit") or None, product=row.get("product") or None,
                method=row.get("method") or None,
                input_class=row.get("input_class") or None,
                pre_harvest_interval_days=int(row["pre_harvest_interval_days"]) if row.get("pre_harvest_interval_days") else None,
                meta_json=json.dumps({"notes": row.get("notes", "")}),
                created_at=utcnow()))
            n += 1
        s.commit()
    touch_source("worker_forms", f"Worker form submissions ({n} rows)", "ok")
    print(f"imported {n} worker records")


if __name__ == "__main__":
    main()
