-- Migration 001: core schema.
-- Types are deliberately portable (REAL/TEXT/INTEGER/ISO-8601 TEXT) so the
-- same schema can move to PostGIS later with minimal changes.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

-- Plots (and estate boundary features, flagged is_boundary=1).
CREATE TABLE IF NOT EXISTS plots (
    plot_id                     INTEGER PRIMARY KEY,
    plot_name                   TEXT NOT NULL,
    estate                      TEXT NOT NULL DEFAULT 'PUL',
    area_ha                     REAL,                      -- computed in UTM 43N (EPSG:32643)
    version                     INTEGER NOT NULL DEFAULT 1,
    is_boundary                 INTEGER NOT NULL DEFAULT 0,
    centroid_lon                REAL,
    centroid_lat                REAL,
    geom_geojson                TEXT NOT NULL,             -- WGS84 GeoJSON polygon
    conversion_organic_start_date TEXT,                    -- ISO date; NULL = not in conversion
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_plots_name ON plots(plot_name, estate);

-- Coffee-year phenology reference table (editable; seeded by migration 002).
CREATE TABLE IF NOT EXISTS calendar_events (
    id                 INTEGER PRIMARY KEY,
    phenostage         TEXT NOT NULL,        -- e.g. 'blossom', 'monsoon', 'harvest'
    month_start        INTEGER NOT NULL,     -- 1-12, inclusive
    month_end          INTEGER NOT NULL,     -- 1-12, inclusive (may wrap, e.g. 12-2)
    typical_activities TEXT,
    notes              TEXT
);

-- Unified management-event table. New record types plug in via event_type
-- values and meta_json, never via new columns on old tables.
CREATE TABLE IF NOT EXISTS management_events (
    id                       INTEGER PRIMARY KEY,
    plot_id                  INTEGER NOT NULL REFERENCES plots(plot_id),
    event_date               TEXT NOT NULL,   -- ISO date
    season                   TEXT,            -- Indian coffee year, e.g. '2024-25' (Oct 1 - Sep 30)
    event_type               TEXT NOT NULL CHECK (event_type IN
        ('harvest','application','pest_observation','field_work','pruning','composting')),
    actor                    TEXT,
    quantity                 REAL,
    unit                     TEXT,
    product                  TEXT,
    method                   TEXT,
    input_class              TEXT CHECK (input_class IS NULL OR input_class IN
        ('organic_allowed','restricted','prohibited')),   -- application rows only
    pre_harvest_interval_days INTEGER,                      -- application rows only
    meta_json                TEXT,
    created_at               TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mgmt_plot_date ON management_events(plot_id, event_date);

-- Registry of observation series (one row per variable+source).
CREATE TABLE IF NOT EXISTS observation_series (
    series_id  INTEGER PRIMARY KEY,
    variable   TEXT NOT NULL,    -- evi, ndvi, ndre, ndre2, ireci, s1_vh, s1_vv, soil_moisture_10cm, ...
    source     TEXT NOT NULL,    -- s2, s1, sensor, manual, dem, canopy
    unit       TEXT,
    UNIQUE (variable, source)
);

-- Generic time-series container: zonal stats AND sensor readings both land here.
CREATE TABLE IF NOT EXISTS plot_observations (
    series_id  INTEGER NOT NULL REFERENCES observation_series(series_id),
    plot_id    INTEGER NOT NULL REFERENCES plots(plot_id),
    ts         TEXT NOT NULL,    -- ISO 8601
    value      REAL,
    valid      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (series_id, plot_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_plot_obs_lookup ON plot_observations(plot_id, series_id, ts);

-- Scene registry: every satellite scene / DEM / canopy raster we cached.
CREATE TABLE IF NOT EXISTS scenes (
    scene_id       TEXT PRIMARY KEY,   -- e.g. 's2_20240315' or the STAC item id
    source         TEXT NOT NULL,      -- s2 | s1 | dem | canopy
    date           TEXT NOT NULL,      -- ISO date
    cloud_pct      REAL,
    cog_path       TEXT,               -- relative to data/processed/
    quicklook_path TEXT,
    meta_json      TEXT
);
CREATE INDEX IF NOT EXISTS idx_scenes_source_date ON scenes(source, date);

-- Week-of-year baselines per plot+series (recomputed by scripts/analyze.py).
CREATE TABLE IF NOT EXISTS baselines (
    series_id  INTEGER NOT NULL,
    plot_id    INTEGER NOT NULL,
    week       INTEGER NOT NULL,       -- ISO week 1-53
    n          INTEGER,
    median     REAL,
    q25        REAL,
    q75        REAL,
    mean       REAL,
    std        REAL,
    p05        REAL,
    p95        REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (series_id, plot_id, week)
);

-- Attention flags (recomputed by scripts/analyze.py).
CREATE TABLE IF NOT EXISTS flags (
    flag_id     INTEGER PRIMARY KEY,
    plot_id     INTEGER NOT NULL REFERENCES plots(plot_id),
    series_id   INTEGER REFERENCES observation_series(series_id),
    scene_date  TEXT,
    rule        TEXT NOT NULL,         -- machine rule id, see app/services/flags.py
    severity    TEXT NOT NULL CHECK (severity IN ('info','amber','red')),
    pctl        REAL,                  -- percentile of current value within week baseline
    z           REAL,                  -- z-score vs week baseline
    message     TEXT NOT NULL,         -- plain-English sentence for the UI
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flags_plot ON flags(plot_id, severity);

-- Offline breakpoint detections (CUSUM scan, see app/services/breaks.py).
CREATE TABLE IF NOT EXISTS breakpoints (
    plot_id     INTEGER NOT NULL,
    series_id   INTEGER NOT NULL,
    break_date  TEXT NOT NULL,
    magnitude   REAL,
    method      TEXT NOT NULL DEFAULT 'cusum',
    PRIMARY KEY (plot_id, series_id, break_date)
);

-- Soil lab results (long format: one row per parameter per sample).
CREATE TABLE IF NOT EXISTS soil_samples (
    sample_id   INTEGER PRIMARY KEY,
    plot_id     INTEGER NOT NULL REFERENCES plots(plot_id),
    sample_date TEXT NOT NULL,
    depth_cm    REAL,
    parameter   TEXT NOT NULL,         -- pH, organic_carbon_pct, N_kg_ha, P2O5_kg_ha, K2O_kg_ha, ...
    value       REAL,
    unit        TEXT,
    lab         TEXT,
    method      TEXT
);
CREATE INDEX IF NOT EXISTS idx_soil_plot ON soil_samples(plot_id, sample_date);

-- Tree census snapshots.
CREATE TABLE IF NOT EXISTS tree_census (
    census_id          INTEGER PRIMARY KEY,
    plot_id            INTEGER NOT NULL REFERENCES plots(plot_id),
    census_date        TEXT NOT NULL,
    tree_count         INTEGER,
    coffee_shade_split TEXT,           -- JSON: {"coffee": 320, "shade": 41}
    source             TEXT,           -- map | drone | manual
    meta_json          TEXT
);

-- Sensor device registry. plot_id NULL = estate-level (e.g. weather station).
CREATE TABLE IF NOT EXISTS sensor_devices (
    device_id    TEXT PRIMARY KEY,
    plot_id      INTEGER REFERENCES plots(plot_id),
    variable     TEXT NOT NULL,
    unit         TEXT,
    location_wkt TEXT
);

-- Ingestion-pipeline registry: one row per data source so the UI can show
-- per-source freshness. New pipelines (weather station, soil lab import...)
-- register a row here; see hooks/README.md.
CREATE TABLE IF NOT EXISTS data_sources (
    source_key  TEXT PRIMARY KEY,      -- s2, s1, dem, canopy, soil, weather, ...
    description TEXT,
    last_run    TEXT,                  -- ISO timestamp of last successful ingest
    status      TEXT                   -- ok | stale | error | never_run
);
