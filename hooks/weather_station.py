#!/usr/bin/env python3
"""Hook stub: weather station feed -> plot_observations (source 'sensor').

Estate-level device: sensor_devices row with plot_id NULL; readings are
broadcast to every plot (or interpolated later). Replace the --simulate loop
with a serial/MQTT read from the actual station.

Usage:  python hooks/weather_station.py --simulate
        python hooks/weather_station.py --port /dev/ttyUSB0   (stub)
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, utcnow  # noqa: E402
from app.db.models import SensorDevice  # noqa: E402
from app.services.pipeline import ensure_series, touch_source, write_plot_obs  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true", help="emit one synthetic reading set")
    ap.add_argument("--port", default=None, help="serial port of the station (not yet implemented)")
    args = ap.parse_args()

    with SessionLocal() as s:
        dev = s.get(SensorDevice, "weather-1")
        if dev is None:
            s.add(SensorDevice(device_id="weather-1", plot_id=None, variable="weather",
                               unit="mixed", location_wkt="POINT(76.084 11.642)"))
            s.commit()

    rain = ensure_series("rainfall_mm", "sensor", "mm")
    temp = ensure_series("temp_c", "sensor", "degC")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.simulate:
        # broadcast one synthetic reading to every plot
        with SessionLocal() as s:
            from app.db.models import Plot

            plots = s.query(Plot).filter(Plot.is_boundary == 0).all()
            for p in plots:
                write_plot_obs(rain, p.plot_id, ts, round(random.uniform(0, 12), 1))
                write_plot_obs(temp, p.plot_id, ts, round(random.uniform(24, 31), 1))
        touch_source("weather", "Weather station feed (simulated)", "ok")
        print(f"simulated weather reading written to {len(plots)} plots at {ts}")
    else:
        print("serial/MQTT ingestion not implemented yet — see hooks/README.md. "
              "Use --simulate to exercise the table pattern.")
        touch_source("weather", "Weather station feed (stub)", "stale")


if __name__ == "__main__":
    main()
