#!/usr/bin/env python3
"""Hook: tree census CSV -> tree_census table.

CSV columns: plot_name, census_date, tree_count, coffee, shade, source
(coffee/shade are split into coffee_shade_split JSON).

Usage:  python hooks/tree_census.py --csv census.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.db.models import Plot, TreeCensus  # noqa: E402
from app.services.pipeline import touch_source  # noqa: E402


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
            split = {"coffee": int(row.get("coffee") or 0), "shade": int(row.get("shade") or 0)}
            s.add(TreeCensus(plot_id=pid, census_date=row["census_date"],
                             tree_count=int(row["tree_count"]) if row.get("tree_count") else None,
                             coffee_shade_split=json.dumps(split),
                             source=row.get("source") or "manual", meta_json=None))
            n += 1
        s.commit()
    touch_source("census", f"Tree census import ({n} rows)", "ok")
    print(f"imported {n} census rows")


if __name__ == "__main__":
    main()
