"""Smoke tests: schema, plot registration, mock pipeline, API endpoints.

Runs against a throwaway data dir (set via env before importing app) so the
real data/ is untouched. Run:  .venv/bin/python -m pytest tests/ -q
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Point the app at a temp data dir BEFORE importing app modules.
_TMP = tempfile.mkdtemp(prefix="mk_test_")
os.environ["DATA_DIR"] = _TMP
os.environ["APP_MODE"] = "mock"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/app.db"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.db import init_db
    from app.services.geo import register_plots
    from app.services.pipeline import register_default_sources
    from app.services import mockdata
    from app.services.geo import derive_bbox, load_geojson

    init_db()
    register_plots()
    register_default_sources()
    bbox = derive_bbox(load_geojson())
    mockdata.generate_s2_mock(bbox, 6, Path(_TMP) / "processed")
    mockdata.generate_s1_mock(bbox, 6, Path(_TMP) / "processed")
    mockdata.generate_dem_canopy_mock(bbox, Path(_TMP) / "processed")
    from scripts.analyze import run_analysis

    run_analysis()

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_plots_registered(client):
    r = client.get("/api/plots").json()
    assert len(r["plots"]) == 38  # 41 features - 3 boundaries
    assert all(p["area_ha"] and p["area_ha"] > 0 for p in r["plots"])
    names = {p["plot_name"] for p in r["plots"]}
    assert "boundary_north_PUL" not in names and "Vellankandi" in names


def test_home_has_phenostage_and_sources(client):
    h = client.get("/api/home").json()
    assert h["phenostage"]["phenostage"]
    keys = {s["source_key"] for s in h["sources"]}
    assert {"s2", "s1", "dem", "canopy"} <= keys


def test_observations_and_baselines(client):
    plots = client.get("/api/plots").json()["plots"]
    pid = next(p["plot_id"] for p in plots if p["plot_name"] == "Vellankandi")
    r = client.get(f"/api/observations?plot_id={pid}&series=ndre&source=s2").json()
    assert len(r["points"]) == 6
    assert all("pctl" in p and "z" in p for p in r["points"])


def test_flags_endpoint(client):
    f = client.get("/api/flags").json()["flags"]
    assert isinstance(f, list)
    for row in f:
        assert row["severity"] in ("red", "amber", "info")
        assert row["message"]


def test_records_crud_and_compliance(client):
    plots = client.get("/api/plots").json()["plots"]
    pid = plots[0]["plot_id"]
    client.put(f"/api/plots/{pid}/conversion", json={"start_date": "2025-01-15"})
    r = client.post(f"/api/plots/{pid}/records", json={
        "event_date": "2026-03-10", "event_type": "application",
        "product": "Endosulfan", "input_class": "prohibited"}).json()
    assert r["compliance"]["ok"] is False
    r2 = client.post(f"/api/plots/{pid}/records", json={
        "event_date": "2026-03-10", "event_type": "application",
        "product": "Neem oil", "input_class": "organic_allowed"}).json()
    assert r2["compliance"]["ok"] is True
    listing = client.get(f"/api/plots/{pid}/records").json()["records"]
    assert len(listing) >= 2
    rid = listing[0]["id"]
    assert client.delete(f"/api/records/{rid}").status_code == 200


def test_inspection_pack_and_export(client, tmp_path):
    plots = client.get("/api/plots").json()["plots"]
    pid = plots[0]["plot_id"]
    r = client.post(f"/api/plots/{pid}/inspection-pack?season=2025-26").json()
    assert Path(r["csv"]).exists() and Path(r["pdf"]).exists()
    z = client.get("/api/export")
    assert z.status_code == 200 and len(z.content) > 1000


def test_maplayer(client):
    m = client.get("/api/maplayer?variable=ndre&source=s2").json()
    assert len(m["points"]) == 38
    assert all(p["status"] in ("red", "amber", "green") for p in m["points"])
