"""Vegetation-index formulas (numpy, reflectance scaled 0-1).

EVI  = 2.5 * (B08 - B04) / (B08 + 6*B04 - 7.5*B02 + 1)
NDVI = (B08 - B04) / (B08 + B04)
NDRE = (B8A - B05) / (B8A + B05)        -- red-edge, first-class early-warning metric
NDRE2= (B07 - B05) / (B07 + B05)        -- B07 variant
IRECI= (B07 - B05) / (B06 - B05) * (B08/B04 - 1) is approximated as NDRE-style
       ratio when only B04/B05/B06/B07/B8A are available; kept optional.

NDRE flags nitrogen/chlorophyll stress before NDVI moves and saturates less
on dense shade canopy, so it is the early-warning layer; NDVI/EVI are the
structural-canopy layer.
"""
from __future__ import annotations

import numpy as np

NODATA = -9999.0


def _ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Safe (a-b)/(a+b) with nodata propagation."""
    out = np.full(a.shape, NODATA, dtype="float32")
    denom = a + b
    ok = (denom != 0) & (a != NODATA) & (b != NODATA)
    out[ok] = (a[ok] - b[ok]) / denom[ok]
    return out


def ndvi(b04: np.ndarray, b08: np.ndarray) -> np.ndarray:
    return _ratio(b08, b04)


def evi(b02: np.ndarray, b04: np.ndarray, b08: np.ndarray) -> np.ndarray:
    out = np.full(b08.shape, NODATA, dtype="float32")
    denom = b08 + 6.0 * b04 - 7.5 * b02 + 1.0
    ok = (denom != 0) & (b02 != NODATA) & (b04 != NODATA) & (b08 != NODATA)
    out[ok] = 2.5 * (b08[ok] - b04[ok]) / denom[ok]
    return out


def ndre(b05: np.ndarray, b8a: np.ndarray) -> np.ndarray:
    return _ratio(b8a, b05)


def ndre2(b05: np.ndarray, b07: np.ndarray) -> np.ndarray:
    return _ratio(b07, b05)


def compute_indices(bands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """bands: {'B02','B04','B05','B06','B07','B08','B8A','B12'} -> index rasters."""
    out = {}
    if all(k in bands for k in ("B04", "B08")):
        out["ndvi"] = ndvi(bands["B04"], bands["B08"])
    if all(k in bands for k in ("B02", "B04", "B08")):
        out["evi"] = evi(bands["B02"], bands["B04"], bands["B08"])
    if all(k in bands for k in ("B05", "B8A")):
        out["ndre"] = ndre(bands["B05"], bands["B8A"])
    if all(k in bands for k in ("B05", "B07")):
        out["ndre2"] = ndre2(bands["B05"], bands["B07"])
    return out
