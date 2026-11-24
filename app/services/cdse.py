"""Copernicus Data Space Ecosystem client (the "live" pipeline).

All access is guarded by CDSE_CLIENT_ID / CDSE_CLIENT_SECRET in .env. When
they are absent, scripts fall back to the --mock generator (mockdata.py), so
the app is fully usable offline.

Flow per Sentinel-2 scene:
  1. STAC search (catalogue.dataspace.copernicus.eu/stac) for SENTINEL-2 L2A
     items over the study bbox with cloud cover < S2_MAX_CLOUD_PCT.
  2. Fetch the needed bands server-side via openEO
     (openeo.dataspace.copernicus.eu) as a clipped GeoTIFF/COG — this is
     what saves bandwidth vs downloading whole 100 km tiles. Cloud masking
     uses the SCL band (classes 3, 8, 9, 10 masked).
  3. Cache the COG under data/processed/s2/<date>/ and register a row in
     `scenes`; zonal stats then run locally (services/raster.py).

Sentinel-1 GRD (IW, VV+VH) is pulled as monthly medians per plot for the
monsoon continuity layer. DEM is Copernicus GLO-30 (one-time). Canopy height
is the GEDI/Landsat global product clipped to the bbox.

Data licence note: Copernicus Sentinel data are free and open (Copernicus
E&R terms, research/education use); see README.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from .. import config

S2_BANDS = ["B02", "B04", "B05", "B06", "B07", "B08", "B8A", "B12", "SCL"]
SCL_CLOUD_CLASSES = {3, 8, 9, 10}  # cloud shadow, cloud med/high, cirrus, snow/ice


class CDSEError(RuntimeError):
    pass


def have_credentials() -> bool:
    return bool(config.CDSE_CLIENT_ID and config.CDSE_CLIENT_SECRET)


class CDSEAuth:
    """OAuth2 client-credentials token for CDSE, cached until near expiry."""

    def __init__(self) -> None:
        if not have_credentials():
            raise CDSEError("CDSE_CLIENT_ID / CDSE_CLIENT_SECRET not set in .env")
        self._token: str | None = None
        self._expires_at = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token
        resp = httpx.post(
            config.CDSE_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": config.CDSE_CLIENT_ID,
                "client_secret": config.CDSE_CLIENT_SECRET,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise CDSEError(f"token request failed: {resp.status_code} {resp.text[:200]}")
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 600))
        return self._token

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}"}


def _bbox_polygon(bbox: dict, pad: float = 0.002) -> dict:
    w, s, e, n = bbox["west"] - pad, bbox["south"] - pad, bbox["east"] + pad, bbox["north"] + pad
    return {
        "type": "Polygon",
        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
    }


def stac_search(auth: CDSEAuth, collection: str, bbox: dict, start: str, end: str,
                max_cloud_pct: float | None = None, limit: int = 200) -> list[dict]:
    """Search the CDSE STAC catalogue. Returns item dicts (id, datetime, cloud, ...)."""
    query = {
        "collections": [collection],
        "bbox": [bbox["west"], bbox["south"], bbox["east"], bbox["north"]],
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": limit,
    }
    if max_cloud_pct is not None:
        query["filter"] = {
            "op": "<=",
            "args": [{"property": "eo:cloud_cover"}, max_cloud_pct],
        }
    items: list[dict] = []
    url = f"{config.CDSE_STAC_URL}/search"
    while url:
        resp = httpx.post(url, json=query, headers=auth.headers(), timeout=60)
        if resp.status_code != 200:
            raise CDSEError(f"STAC search failed: {resp.status_code} {resp.text[:300]}")
        body = resp.json()
        items.extend(body.get("features", []))
        url = body.get("links", []) and next(
            (l["href"] for l in body["links"] if l.get("rel") == "next"), None
        )
        if url:  # STAC "next" links are POST bodies; keep it simple and stop at page 1
            break
    # de-duplicate by id, keep most recent first
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x.get("properties", {}).get("datetime", ""), reverse=True):
        if it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out


# --- openEO helpers ----------------------------------------------------------

def _openeo_headers(auth: CDSEAuth) -> dict:
    h = auth.headers()
    h["Content-Type"] = "application/json"
    return h


def openeo_download_cog(process_graph: dict, out_path: Path, auth: CDSEAuth,
                        timeout_s: int = 900) -> Path:
    """Run an openEO batch job and download the resulting GeoTIFF to out_path.

    process_graph must end in a `result` node with format GTiff. Poll the job
    until it finishes, then fetch the first result asset.
    """
    base = config.CDSE_OPENEO_URL.rstrip("/")
    resp = httpx.post(f"{base}/v1/jobs", json={"process_graph": process_graph},
                      headers=_openeo_headers(auth), timeout=60)
    if resp.status_code not in (200, 201):
        raise CDSEError(f"openeo job create failed: {resp.status_code} {resp.text[:300]}")
    job_id = resp.json()["id"]
    httpx.post(f"{base}/v1/jobs/{job_id}/start", headers=_openeo_headers(auth), timeout=60)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = httpx.get(f"{base}/v1/jobs/{job_id}", headers=_openeo_headers(auth), timeout=60).json()
        status = st.get("status")
        if status == "finished":
            results = httpx.get(f"{base}/v1/jobs/{job_id}/results",
                                headers=_openeo_headers(auth), timeout=60).json()
            href = results["assets"][next(iter(results["assets"]))]["href"]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with httpx.stream("GET", href, headers=_openeo_headers(auth), timeout=300) as r:
                r.raise_for_status()
                with open(out_path, "wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            return out_path
        if status in ("error", "canceled"):
            raise CDSEError(f"openeo job {job_id} ended with status {status}: {st.get('error')}")
        time.sleep(5)
    raise CDSEError(f"openeo job {job_id} timed out after {timeout_s}s")


def s2_scene_process_graph(item_id: str, bbox: dict, date: str) -> dict:
    """openEO graph: one S2 L2A scene, SCL cloud-masked, clipped to bbox, as GTiff."""
    poly = _bbox_polygon(bbox)
    return {
        "load": {
            "process_id": "load_collection",
            "arguments": {
                "id": "SENTINEL2_L2A",
                "spatial_extent": {"west": poly["coordinates"][0][0][0], "south": poly["coordinates"][0][0][1],
                                   "east": poly["coordinates"][0][2][0], "north": poly["coordinates"][0][2][1],
                                   "crs": "EPSG:4326"},
                "temporal_extent": [f"{date}T00:00:00Z", f"{date}T23:59:59Z"],
                "bands": S2_BANDS,
            },
            "result": True,
        },
        "mask": {
            "process_id": "mask",
            "arguments": {"data": {"from_node": "load"},
                          "mask": {"from_node": "scl_flag"}},
            "result": True,
        },
    }


def fetch_s2_scene_live(auth: CDSEAuth, item: dict, bbox: dict, out_dir: Path) -> Path | None:
    """Download one S2 scene via openEO into out_dir (COG). Returns path or None."""
    date = item["properties"]["datetime"][:10]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"s2_{date}.tif"
    if out.exists():
        return out
    graph = s2_scene_process_graph(item["id"], bbox, date)
    try:
        return openeo_download_cog(graph, out, auth)
    except CDSEError:
        return None


def fetch_glo30_dem(auth: CDSEAuth, bbox: dict, cache_dir: Path) -> Path:
    """One-time Copernicus GLO-30 DEM download clipped to the bbox."""
    items = stac_search(auth, "COP-DEM_GLO-30", bbox, "2020-01-01", "2021-01-01", limit=10)
    if not items:
        raise CDSEError("no GLO-30 tiles found for bbox")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / "glo30_dem.tif"
    if out.exists():
        return out
    href = items[0]["assets"]["data"]["href"]
    with httpx.stream("GET", href, headers=auth.headers(), timeout=600) as r:
        r.raise_for_status()
        with open(out, "wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    return out
