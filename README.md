# Maniyamkode Coffee — local farm monitoring app

Local-first monitoring web app (~38 plots + 3 boundary features from
`data/PUL_plots.geojson`).


Stack: **Python 3.12+ / FastAPI** backend, **plain HTML+JS (Leaflet + Chart.js,
vendored in `static/vendor/`, no Node build step)** frontend, **one local
SQLite file** + local raster cache. Runs on macOS now; designed to move to a
headless Linux mini-PC later (everything is re-pointable via `.env`).

## Quick start (macOS, mock data — no credentials needed)

```bash
# 1. install uv (https://docs.astral.sh/uv/) then:
uv venv --python 3.12 .venv && uv pip install -e .[dev]   # or: uv sync
# (equivalently: python3 -m venv .venv && .venv/bin/pip install -e .)

# 2. config
cp .env.example .env        # APP_MODE=mock works out of the box

# 3. database + plots + synthetic satellite pull (36 months) + analysis
.venv/bin/python scripts/init_db.py
.venv/bin/python scripts/preload.py --mock

# 4. run the app
.venv/bin/uvicorn app.main:app --port 8000
# open http://127.0.0.1:8000
```

`--mock` fakes Sentinel-2/Sentinel-1/DEM/canopy rasters locally (with a few
scripted anomalies so the attention view has something to show). The real
pipeline is used when `APP_MODE=live` and CDSE credentials are present.

## Real data: Copernicus Data Space Ecosystem (CDSE)

1. Create a free account at <https://dataspace.copernicus.eu>.
2. Register an OAuth2 client (account → OAuth2 clients, grant type
   `client_credentials`) and copy the client id/secret into `.env`
   (`CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET`).
3. Set `APP_MODE=live` in `.env` and run:

```bash
.venv/bin/python scripts/preload.py            # full 36-month pull (idempotent, resumable)
.venv/bin/python scripts/update.py             # incremental scenes + re-analysis (cron this)
.venv/bin/python scripts/analyze.py            # baselines + flags + breakpoints only
.venv/bin/python scripts/export_all.py         # one-click zip: all tables as CSV + GeoJSON
```

Pipeline: STAC search (`catalogue.dataspace.copernicus.eu/stac`) for
Sentinel-2 L2A scenes < 40% cloud over the study bbox → server-side clipped,
SCL-cloud-masked (classes 3,8,9,10) COGs via openEO
(`openeo.dataspace.copernicus.eu`) → local index computation
(NDVI, EVI, **NDRE**, NDRE2) → per-plot zonal means into `plot_observations`.
Sentinel-1 GRD (VV+VH) monthly medians carry the Jun–Sep monsoon signal when
optical is blinded (the UI marks this substitution). DEM = Copernicus GLO-30
(one-time clip, per-plot elevation/slope + hillshade). Canopy height = GEDI/
Landsat global raster clipped to the bbox (pluggable: a drone canopy model can
replace it later).

**Data licence:** Copernicus Sentinel data are free and open under the
Copernicus E&R terms (research/education use); GLO-30 likewise. See
<https://dataspace.copernicus.eu/licence>.

## Using the app

- **Home / attention view** — top strip: estate, current phenostage (from the
  editable `calendar_events` table), monsoon status, per-source data
  freshness. Main list: ranked plot-level flags, worst first, each with a
  plain-English status and sparkline. Click → map flies to the plot, drawer
  opens.
- **Map** — Leaflet. Plots coloured by the selected metric's status vs the
  same week in past years (red < 5th pctl, amber 5–25th, green normal).
  Metric switcher: NDRE, EVI, NDVI, S1-VH, canopy height, elevation, slope,
  area. Time slider over monthly composites; scene archive grid; boundary
  toggle; compare mode (two dates side-by-side, e.g. pre/post-pruning NDRE).
- **Plot drawer** — Overview (area, terrain, canopy, organic-conversion
  status, status chips), Season (season-over-season overlays aligned by
  day-of-season, CUSUM change-points, management events), Imagery (per-plot
  quicklook gallery), Records (add harvest/application/pest/field-work
  entries; applications are checked against the plot's conversion status and
  non-conforming ones are blocked/flagged; **Inspection pack** exports the
  plot-season as CSV+PDF for NPOP organic inspection), Soil & census (tables
  the soil/tree ingest writes to).

## Architecture

```
app/
  config.py            paths, .env, thresholds
  main.py / api.py     FastAPI app + REST endpoints
  db/                  engine + numbered SQL migrations (db/migrations/) + models/ (one file per domain)
  services/
    geo.py             GeoJSON load, bbox, UTM 43N areas, plot registration
    cdse.py            CDSE auth, STAC search, openEO downloads (live pipeline)
    mockdata.py        synthetic raster pipeline (--mock)
    indices.py         NDVI/EVI/NDRE/NDRE2 formulas
    raster.py          COG writing, zonal stats, quicklooks
    pipeline.py        shared ingest helpers (series registry, observations, sources)
    baselines.py       week-of-year baselines (median/MAD robust stats)
    flags.py           attention flags (plain-English messages)
    breaks.py          CUSUM breakpoint scan
    season.py          Indian coffee year (Oct 1–Sep 30) helpers
    organic.py         conversion compliance checks
    inspection.py      NPOP inspection pack (CSV+PDF)
    export.py          export-everything zip
scripts/               init_db, preload, update, analyze, export_all
hooks/                 stubs+docs: weather station, soil sensors, tree census, worker forms
static/                frontend (vendored Leaflet/Chart.js, no build step)
data/                  PUL_plots.geojson (source), app.db, processed/ (COGs+quicklooks), exports/
```

### Database schema (SQLite now, PostGIS-ready)

Portable types only (REAL/TEXT/INTEGER, ISO-8601 timestamps). Source of truth
is the numbered SQL in `app/db/migrations/`; ORM models mirror it.

- `plots` — plot_id, name, estate, area_ha (UTM 43N), centroid, geom, boundary
  flag, `conversion_organic_start_date`
- `calendar_events` — phenostage, month range, typical activities (editable)
- `management_events` — unified records (harvest/application/pest/field_work/
  pruning/composting) + input_class + PHI for applications
- `observation_series` + `plot_observations` — generic series container
  (zonal stats *and* sensor readings); index (plot_id, series_id, ts)
- `scenes`, `baselines`, `flags`, `breakpoints` — derived/cache tables
- `soil_samples`, `tree_census`, `sensor_devices`, `data_sources` — registry +
  long-format tables that hooks write to

New data types plug into these tables — never into new columns on old tables.

### API

`GET /api/home` (attention summary) · `/api/plots` · `/api/plots/{id}` ·
`/api/observations?plot_id&series&source&from&to` · `/api/flags` ·
`/api/scenes?source` · `/api/maplayer?variable&source&date` ·
`/api/plots/{id}/season|soil|records` · `POST /api/plots/{id}/records` ·
`DELETE /api/records/{id}` · `PUT /api/plots/{id}/conversion` ·
`POST /api/plots/{id}/inspection-pack` · `GET /api/export` (zip) ·
`/api/calendar` · `/api/series`. Static rasters served read-only under
`/processed/`.

## Moving to the headless mini-PC

Everything lives under paths from `.env`: set `DATA_DIR=/mnt/data` (or a
mounted disk), copy `data/` + `.env`, `uv sync`, then run
`uvicorn app.main:app --host 0.0.0.0` under systemd, and cron
`scripts/update.py` nightly. SQLite WAL mode is enabled; for many plots/years
the same schema ports to PostGIS (swap the migration runner for Alembic).

## Tests

```bash
.venv/bin/python -m pytest tests/ -q    # 7 smoke tests on a throwaway mock dataset
```
