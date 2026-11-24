"""FastAPI application entrypoint.

Run with:  uvicorn app.main:app --reload     (see README)
Serves the static frontend from static/ and the JSON API from app/api.py.
Processed rasters/quicklooks are served under /processed/ (read-only).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config
from .api import router
from .db import init_db

app = FastAPI(title="Maniyamkode Coffee — farm monitoring", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    init_db()


app.include_router(router)

# processed rasters + quicklooks (read-only mount)
app.mount("/processed", StaticFiles(directory=config.PROCESSED_DIR), name="processed")

# frontend
static = config.STATIC_DIR
app.mount("/static", StaticFiles(directory=static), name="static")


@app.get("/")
def index():
    from fastapi.responses import FileResponse

    return FileResponse(static / "index.html")
