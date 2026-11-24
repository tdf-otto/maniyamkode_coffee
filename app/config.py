"""Central configuration: paths, .env loading, constants.

Everything the app needs to know about where things live is here, so the
whole app can be re-pointed at the headless mini-PC later just by editing
`.env` (or the defaults below). No magic paths anywhere else.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Repo root = parent of the `app/` package directory.
ROOT = Path(__file__).resolve().parent.parent

# Load .env from the repo root if present (never required; defaults work).
load_dotenv(ROOT / ".env")


def _env_path(name: str, default: str) -> Path:
    """Resolve a data path relative to the repo root unless absolute."""
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else ROOT / p


# --- Paths ------------------------------------------------------------------
DATA_DIR = _env_path("DATA_DIR", "data")
DB_PATH = DATA_DIR / "app.db"
# The plot geometry is source data that ships with the repo — it stays in the
# repo's data/ even if DATA_DIR is re-pointed (e.g. tests, mini-PC data disk).
GEOJSON_PATH = Path(os.getenv("GEOJSON_PATH", str(ROOT / "data" / "PUL_plots.geojson")))
PROCESSED_DIR = DATA_DIR / "processed"          # COGs + quicklooks per source/date
CACHE_DIR = DATA_DIR / "cache"                  # raw downloads (S2 tiles, DEM, canopy)
EXPORT_DIR = DATA_DIR / "exports"               # zip bundles from export_all
STATIC_DIR = ROOT / "static"

# --- Database ---------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# --- Copernicus Data Space Ecosystem ----------------------------------------
CDSE_CLIENT_ID = os.getenv("CDSE_CLIENT_ID", "")
CDSE_CLIENT_SECRET = os.getenv("CDSE_CLIENT_SECRET", "")
CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.com/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
CDSE_STAC_URL = "https://catalogue.dataspace.copernicus.eu/stac"
CDSE_OPENEO_URL = "https://openeo.dataspace.copernicus.eu"

# "mock" = synthetic rasters, no network, for UI development.
# "live" = real CDSE downloads (requires CDSE_CLIENT_ID/SECRET).
APP_MODE = os.getenv("APP_MODE", "mock").lower()

# --- Domain constants --------------------------------------------------------
# Indian coffee year runs Oct 1 -> Sep 30 (harvest Dec-Feb sits inside it).
COFFEE_YEAR_START_MONTH = 10  # October
COFFEE_YEAR_START_DAY = 1

# Sentinel-2 L2A scene selection: keep scenes below this cloud cover.
S2_MAX_CLOUD_PCT = float(os.getenv("S2_MAX_CLOUD_PCT", "40"))
# How far back the first pull reaches.
PRELOAD_MONTHS = int(os.getenv("PRELOAD_MONTHS", "36"))

# Flagging thresholds (section 6 of the build prompt). All overridable here.
FLAG_ZSCORE = -2.0            # z <= this -> below historical range
FLAG_PCTL = 5                 # below 5th percentile of the same week
FLAG_SUSTAINED_PCTL_DROP = 20 # sustained drop >20 pctl over 2 acquisitions
FLAG_S1_MONSOON_MONTHS = (6, 7, 8, 9)  # Jun-Sep: Sentinel-1 carries the signal


def ensure_dirs() -> None:
    """Create all data directories if missing (safe to call repeatedly)."""
    for d in (DATA_DIR, PROCESSED_DIR, CACHE_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
