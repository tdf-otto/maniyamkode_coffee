# Hooks — plugging new data sources into the existing tables

Every new data type plugs into an **existing** table; no schema surgery on old
tables is ever needed. Register your pipeline in `data_sources` (via
`app.services.pipeline.touch_source`) so the home screen shows its freshness.

| Hook | Writes to | How to run |
|---|---|---|
| `weather_station.py` | `sensor_devices` (device, plot_id NULL) + `plot_observations` (series source `sensor`, e.g. `rainfall_mm`, `temp_c`) | `python hooks/weather_station.py --port /dev/ttyUSB0` or `--file csv` |
| `soil_sensors.py` | `plot_observations` (e.g. `soil_moisture_10cm`, source `sensor`) | `python hooks/soil_sensors.py --simulate` |
| `tree_census.py` | `tree_census` | `python hooks/tree_census.py --csv census.csv` |
| `worker_forms.py` | `management_events` | `python hooks/worker_forms.py --csv submissions.csv` (phone-submitted records land here) |
| soil lab import | `soil_samples` | `python hooks/tree_census.py`-style CSV import; see `soil_samples` long format |

Pattern for a new hook:

```python
from app.db import SessionLocal, utcnow
from app.db.models import PlotObservation
from app.services.pipeline import ensure_series, write_plot_obs, touch_source

series_id = ensure_series("rainfall_mm", "sensor", "mm")
# for each reading: write_plot_obs(series_id, plot_id, ts, value)
touch_source("weather", "Weather station feed", "ok")
```

Then run `python scripts/analyze.py` so baselines/flags pick up the new series.
