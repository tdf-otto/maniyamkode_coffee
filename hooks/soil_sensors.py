#!/usr/bin/env python3
"""Hook stub: soil-moisture sensors -> plot_observations (source 'sensor').

Each sensor is a sensor_devices row tied to one plot; readings land in
plot_observations as variable 'soil_moisture_10cm' (unit m3/m3), which the
analysis pipeline treats like any other series (baselines + flags).

Usage:  python hooks/soil_sensors.py --simulate
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.db.models import Plot, SensorDevice  # noqa: E402
from app.services.pipeline import ensure_series, touch_source, write_plot_obs  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true")
    args = ap.parse_args()
    if not args.simulate:
        print("sensor read loop not implemented yet — use --simulate; see hooks/README.md")
        return
    sm = ensure_series("soil_moisture_10cm", "sensor", "m3/m3")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with SessionLocal() as s:
        plots = s.query(Plot).filter(Plot.is_boundary == 0).all()
        for p in plots:
            dev = s.get(SensorDevice, f"sm-{p.plot_id}")
            if dev is None:
                s.add(SensorDevice(device_id=f"sm-{p.plot_id}", plot_id=p.plot_id,
                                   variable="soil_moisture_10cm", unit="m3/m3",
                                   location_wkt=f"POINT({p.centroid_lon} {p.centroid_lat})"))
            write_plot_obs(sm, p.plot_id, ts, round(random.uniform(0.18, 0.34), 3))
        s.commit()
    touch_source("sensors", "Soil-moisture sensors (simulated)", "ok")
    print(f"simulated soil-moisture readings written at {ts}")


if __name__ == "__main__":
    main()
