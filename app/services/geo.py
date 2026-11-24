"""Spatial core: load PUL_plots.geojson, derive the study bbox, register plots.

- Features whose plot_name starts with "boundary" or equals "(SW exclave)"
  are estate boundaries (is_boundary=1): styled differently in the UI and
  excluded from plot lists by default.
- Area is computed in UTM 43N (EPSG:32643), the correct zone for Wayanad
  (76.08 E, 11.64 N). Centroids are stored in WGS84 for Leaflet.
"""
from __future__ import annotations

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform

from .. import config
from ..db import SessionLocal, utcnow
from ..db.models import Plot

# WGS84 lon/lat -> UTM 43N metres. Wayanad sits in UTM zone 43N.
_TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

BOUNDARY_PREFIX = "boundary"
BOUNDARY_NAMES = {"(SW exclave)"}


def is_boundary_name(plot_name: str) -> bool:
    return plot_name.startswith(BOUNDARY_PREFIX) or plot_name in BOUNDARY_NAMES


def load_geojson(path: Path | None = None) -> dict:
    path = path or config.GEOJSON_PATH
    return json.loads(Path(path).read_text())


def derive_bbox(fc: dict) -> dict:
    """Study bbox (WGS84) from all features: {west, south, east, north}."""
    xs, ys = [], []

    def walk(coords):
        if isinstance(coords[0], (int, float)):
            xs.append(coords[0])
            ys.append(coords[1])
        else:
            for c in coords:
                walk(c)

    for f in fc["features"]:
        walk(f["geometry"]["coordinates"])
    return {"west": min(xs), "south": min(ys), "east": max(xs), "north": max(ys)}


def area_ha(geom_geojson: str) -> float:
    """Polygon area in hectares via UTM 43N."""
    geom = shape(json.loads(geom_geojson))
    utm = transform(lambda x, y, z=None: _TO_UTM.transform(x, y), geom)
    return utm.area / 10_000.0


def centroid_lonlat(geom_geojson: str) -> tuple[float, float]:
    geom = shape(json.loads(geom_geojson))
    c = geom.centroid
    return c.x, c.y


def register_plots() -> dict:
    """(Re)populate the plots table from the GeoJSON. Idempotent.

    Returns a summary dict {plots: n, boundaries: n, bbox: ...}.
    Existing plot_ids are preserved when plot_name+estate match, so foreign
    keys in other tables stay valid across re-runs.
    """
    fc = load_geojson()
    bbox = derive_bbox(fc)
    now = utcnow()
    n_plots = n_bounds = 0
    with SessionLocal() as s:
        existing = {(p.plot_name, p.estate): p for p in s.query(Plot).all()}
        for feat in fc["features"]:
            props = feat.get("properties", {})
            name = props.get("plot_name") or "unnamed"
            estate = props.get("estate") or "PUL"
            version = int(props.get("version") or 1)
            geom_json = json.dumps(feat["geometry"])
            boundary = 1 if is_boundary_name(name) else 0
            lon, lat = centroid_lonlat(geom_json)
            row = existing.get((name, estate))
            if row is None:
                row = Plot(plot_id=None, created_at=now)
                s.add(row)
            row.plot_name = name
            row.estate = estate
            row.version = version
            row.is_boundary = boundary
            row.area_ha = None if boundary else round(area_ha(geom_json), 3)
            row.centroid_lon = round(lon, 7)
            row.centroid_lat = round(lat, 7)
            row.geom_geojson = geom_json
            row.updated_at = now
            if boundary:
                n_bounds += 1
            else:
                n_plots += 1
        s.commit()
    return {"plots": n_plots, "boundaries": n_bounds, "bbox": bbox}


def plot_geometries() -> list[dict]:
    """All plot geometries as shapely shapes with plot_id, for zonal stats."""
    out = []
    with SessionLocal() as s:
        for p in s.query(Plot).all():
            out.append(
                {
                    "plot_id": p.plot_id,
                    "plot_name": p.plot_name,
                    "is_boundary": p.is_boundary,
                    "geom": shape(json.loads(p.geom_geojson)),
                }
            )
    return out


def geojson_response(include_boundaries: bool = True) -> dict:
    """FeatureCollection for the API, with derived area/centroid attached."""
    feats = []
    with SessionLocal() as s:
        q = s.query(Plot)
        if not include_boundaries:
            q = q.filter(Plot.is_boundary == 0)
        for p in q.all():
            feats.append(
                {
                    "type": "Feature",
                    "properties": {
                        "plot_id": p.plot_id,
                        "plot_name": p.plot_name,
                        "estate": p.estate,
                        "area_ha": p.area_ha,
                        "version": p.version,
                        "is_boundary": bool(p.is_boundary),
                        "conversion_organic_start_date": p.conversion_organic_start_date,
                    },
                    "geometry": json.loads(p.geom_geojson),
                }
            )
    return {"type": "FeatureCollection", "features": feats}


def bbox_geojson(bbox: dict, pad: float = 0.002) -> str:
    """bbox as a WGS84 polygon GeoJSON string (used to clip downloads)."""
    w, s_, e, n = bbox["west"] - pad, bbox["south"] - pad, bbox["east"] + pad, bbox["north"] + pad
    ring = [[w, s_], [e, s_], [e, n], [w, n], [w, s_]]
    return json.dumps({"type": "Polygon", "coordinates": [ring]})


def reproject_to_utm(geom_json: str) -> str:
    """GeoJSON string in UTM 43N metres (helper for raster masking)."""
    geom = transform(lambda x, y, z=None: _TO_UTM.transform(x, y), shape(json.loads(geom_json)))
    return json.dumps(mapping(geom))
