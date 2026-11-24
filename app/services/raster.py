"""Raster I/O: write COGs, compute zonal stats per plot, render quicklook PNGs.

All processed rasters live under data/processed/<source>/<date>/ as Cloud
Optimized GeoTIFFs; quicklooks are small PNGs beside them. Everything is
cached — nothing is fetched twice (scene rows in the `scenes` table track
what exists on disk).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.warp import transform as warp_transform
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform

from .. import config
from .indices import NODATA

_TO_RASTER_SRC = {}  # cache of transformers per CRS string


def _to_crs(geom_wgs84_json: str, dst_crs: CRS):
    """Reproject a WGS84 GeoJSON geometry into the raster's CRS."""
    key = str(dst_crs)
    if key not in _TO_RASTER_SRC:
        _TO_RASTER_SRC[key] = Transformer.from_crs("EPSG:4326", key, always_xy=True)
    t = _TO_RASTER_SRC[key]
    return shapely_transform(lambda x, y, z=None: t.transform(x, y), shape(json.loads(geom_wgs84_json)))


def write_cog(path: Path, bands: list[np.ndarray], transform, crs: str = "EPSG:4326",
              nodata: float = NODATA, band_names: list[str] | None = None) -> Path:
    """Write a multi-band COG (float32). Returns path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = bands[0].shape
    profile = dict(
        driver="GTiff",
        height=h,
        width=w,
        count=len(bands),
        dtype="float32",
        crs=CRS.from_user_input(crs),
        transform=transform,
        nodata=nodata,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
    )
    with rasterio.open(path, "w", **profile) as dst:
        for i, b in enumerate(bands, start=1):
            dst.write(b.astype("float32"), i)
            if band_names:
                dst.set_band_description(i, band_names[i - 1])
    return path


def zonal_mean(raster_path: Path, geom_wgs84_json: str, band: int = 1) -> float | None:
    """Mean of valid (non-nodata) pixels of `band` inside the plot polygon."""
    with rasterio.open(raster_path) as src:
        geom = _to_crs(geom_wgs84_json, src.crs)
        if geom.is_empty:
            return None
        mask = rasterize(
            [(mapping(geom), 1)],
            out_shape=(src.height, src.width),
            transform=src.transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        ).astype(bool)
        if not mask.any():
            return None
        data = src.read(band, masked=True)
        vals = data[mask].compressed()  # plot pixels only, nodata excluded
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            return None
        return float(np.mean(vals))


def zonal_stats_all_bands(raster_path: Path, geom_wgs84_json: str) -> dict[str, float]:
    """Mean of every band in the raster, keyed by band description (or bandN)."""
    out: dict[str, float] = {}
    with rasterio.open(raster_path) as src:
        geom = _to_crs(geom_wgs84_json, src.crs)
        mask = rasterize(
            [(mapping(geom), 1)],
            out_shape=(src.height, src.width),
            transform=src.transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        ).astype(bool)
        if not mask.any():
            return out
        for i in range(1, src.count + 1):
            data = src.read(i, masked=True)
            vals = data[mask].compressed()
            vals = vals[np.isfinite(vals)]
            if vals.size:
                name = src.descriptions[i - 1] or f"band{i}"
                out[name] = float(np.mean(vals))
    return out


def _stretch(arr: np.ndarray, lo_pct=2, hi_pct=98) -> np.ndarray:
    valid = arr[np.isfinite(arr) & (arr != NODATA)]
    if valid.size == 0:
        return np.zeros(arr.shape, dtype="uint8")
    lo, hi = np.percentile(valid, [lo_pct, hi_pct])
    if hi <= lo:
        hi = lo + 1e-6
    out = np.clip((arr - lo) / (hi - lo), 0, 1)
    out[~np.isfinite(arr) | (arr == NODATA)] = 0
    return (out * 255).astype("uint8")


def quicklook_gray(arr: np.ndarray, path: Path, invert: bool = False) -> Path:
    from PIL import Image

    g = _stretch(arr)
    if invert:
        g = 255 - g
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(g, mode="L").save(path)
    return path


def quicklook_rgb(r: np.ndarray, g: np.ndarray, b: np.ndarray, path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    img = np.dstack([_stretch(r), _stretch(g), _stretch(b)])
    Image.fromarray(img, mode="RGB").save(path)
    return path


def ndre_colormap(arr: np.ndarray, path: Path) -> Path:
    """Traffic-light-ish RdYlGn quicklook for NDRE/NDVI-style indices in [-1, 1]."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.clip((arr + 1) / 2, 0, 1)  # -1..1 -> 0..1
    valid = np.isfinite(arr) & (arr != NODATA)
    # simple green ramp: low=red, high=green
    r = ((1 - a) * 220).astype("uint8")
    g = (a * 180 + 40).astype("uint8")
    b = ((1 - a) * 60).astype("uint8")
    img = np.dstack([r, g, b]).astype("uint8")
    img[~valid] = 40
    Image.fromarray(img, mode="RGB").save(path)
    return path


def read_band(raster_path: Path, band: int = 1) -> tuple[np.ndarray, object, CRS]:
    with rasterio.open(raster_path) as src:
        return src.read(band), src.transform, src.crs


def bbox_transform(bbox: dict, res_deg: float = 10 / 111320.0) -> tuple[object, int, int]:
    """Affine transform + shape for a raster covering bbox at ~res_deg degrees."""
    from rasterio.transform import from_origin

    w, s_, e, n = bbox["west"], bbox["south"], bbox["east"], bbox["north"]
    width = int(round((e - w) / res_deg))
    height = int(round((n - s_) / res_deg))
    return from_origin(w, n, res_deg, res_deg), width, height
