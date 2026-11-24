"""One-click "export everything": a zip of all tables as CSV + plots GeoJSON + config.

Data sovereignty: the whole estate's data leaves the machine only when the
user explicitly runs this.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect as sa_inspect, select, text

from .. import config
from ..db import engine, SessionLocal
from .geo import geojson_response


def export_all_zip(out_path: Path | None = None) -> Path:
    config.ensure_dirs()
    if out_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = config.EXPORT_DIR / f"maniyamkode_export_{stamp}.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as s:
        table_names = [t for t in sa_inspect(engine).get_table_names()
                       if t != "schema_migrations"]
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # every table as CSV
            for tname in sorted(table_names):
                rows = s.execute(text(f"SELECT * FROM {tname}")).mappings().all()
                buf = io.StringIO()
                if rows:
                    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
                zf.writestr(f"csv/{tname}.csv", buf.getvalue())
            # plots as GeoJSON (boundaries included)
            zf.writestr("geojson/plots.geojson", json.dumps(geojson_response(True), indent=1))
            # schema + config for reproducibility
            mig = sorted((config.ROOT / "app/db/migrations").glob("*.sql"))
            for m in mig:
                zf.writestr(f"schema/{m.name}", m.read_text())
            zf.writestr("config/README.txt",
                        "Export produced by scripts/export_all.py. "
                        "All timestamps ISO-8601 UTC. Areas in hectares (UTM 43N). "
                        "Copernicus Sentinel data: free and open under Copernicus E&R terms.")
    return out_path
