"""Synthetic data generator (--mock mode).

Produces the same artefacts as the live CDSE pipeline — per-scene COGs with
index bands, quicklook PNGs, S1 monthly backscatter, DEM and canopy rasters,
plus zonal statistics in plot_observations — so the whole UI can be developed
and demoed without credentials. A few plots get deliberate anomalies (recent
NDRE drop, a mid-history step change, a monsoon S1 spike) so the attention
view has something real to show.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import rasterio
from scipy.ndimage import gaussian_filter

from .. import config
from ..db import SessionLocal, utcnow
from ..db.models import Plot, Scene
from . import raster as rio
from .indices import NODATA, compute_indices

rng = np.random.default_rng(42)

# Plots that get scripted anomalies (by plot_name) so flags/breaks are visible.
ANOMALY_NDRE_DROP = {"Vellankandi", "Kulam"}     # recent NDRE decline
ANOMALY_STEP = {"MK-2"}                           # step change ~8 months ago
ANOMALY_S1 = {"Paambkutt"}                        # monsoon backscatter spike


def _monthly_dates(months: int) -> list[date]:
    """Calendar-month midpoints (15th), oldest first — keeps ISO weeks stable
    year over year so week-of-year baselines stay tight."""
    today = date.today().replace(day=1)
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        out.append(date(y, m, 15))
    out.sort()  # oldest first; dates[-3:] = the three most recent months
    return out


def _plot_masks(bbox: dict, res: float):
    """Rasterize plots into a label array (0 = outside plots)."""
    transform, w, h = rio.bbox_transform(bbox, res)
    labels = np.zeros((h, w), dtype="int32")
    names: dict[int, str] = {}
    with SessionLocal() as s:
        plots = s.query(Plot).filter(Plot.is_boundary == 0).all()
        geoms = [(p.plot_id, json.loads(p.geom_geojson)) for p in plots]
    from rasterio.features import rasterize

    shapes = []
    for pid, gj in geoms:
        from shapely.geometry import shape

        shapes.append((shape(gj).__geo_interface__, pid))
        names[pid] = next(n for i, n in [(p.plot_id, p.plot_name) for p in plots] if i == pid)
    if shapes:
        labels = rasterize(shapes, out_shape=(h, w), transform=transform, fill=0, dtype="int32")
    return transform, w, h, labels, names


def _seasonal(month: int) -> dict:
    """Crude Wayanad seasonality: greenness peaks post-monsoon, dips pre-monsoon."""
    g = 0.62 + 0.16 * np.sin(2 * np.pi * (month - 1) / 12.0)  # canopy vigour
    n = 0.55 + 0.13 * np.sin(2 * np.pi * (month - 2) / 12.0)  # nitrogen signal, offset phase
    wet = 1.0 if month in (6, 7, 8, 9) else 0.0
    return {"g": g, "n": n, "wet": wet}


def generate_s2_mock(bbox: dict, months: int, processed_root: Path) -> int:
    """Write monthly mock S2 scenes + zonal stats. Returns scene count."""
    res = 10 / 111320.0
    transform, w, h, labels, names = _plot_masks(bbox, res)
    plot_ids = sorted(names)
    # per-plot vigour offsets so plots genuinely differ
    offsets = {pid: rng.normal(0, 0.05) for pid in plot_ids}
    ndre_drop_plots = {pid for pid, n in names.items() if n in ANOMALY_NDRE_DROP}
    step_plots = {pid for pid, n in names.items() if n in ANOMALY_STEP}
    dates = _monthly_dates(months)
    step_date = dates[max(0, len(dates) - 8)]

    from .pipeline import record_scene_observations, scene_exists

    n_scenes = 0
    for d in dates:
        if scene_exists(f"s2_{d.isoformat()}"):  # resumable: skip cached scenes
            continue
        season = _seasonal(d.month)
        base = gaussian_filter(rng.normal(0, 1, (h, w)), sigma=8)  # smooth spatial noise
        px_plot = labels
        # per-pixel greenness: base + plot offset (+ scripted anomalies)
        g = np.full((h, w), season["g"], dtype="float32") + 0.05 * base + rng.normal(0, 0.008)
        n_sig = np.full((h, w), season["n"], dtype="float32") + 0.04 * base + rng.normal(0, 0.008)
        for pid in plot_ids:
            m = px_plot == pid
            g[m] += offsets[pid]
            n_sig[m] += offsets[pid] * 0.8
            if pid in ndre_drop_plots and d >= dates[-3]:
                n_sig[m] -= 0.22 * (dates.index(d) - (len(dates) - 3) + 1) / 3.0  # sustained drop
            if pid in step_plots and d >= step_date:
                g[m] -= 0.14
                n_sig[m] -= 0.10
        g = np.clip(g, 0.2, 0.95)
        n_sig = np.clip(n_sig, 0.15, 0.9)
        # reflectance model: healthy canopy -> high NIR, low red; NIR-red gap ~ greenness
        b08 = 0.25 + 0.35 * g
        b04 = 0.10 - 0.05 * g + 0.01 * base
        b02 = 0.05 - 0.02 * g
        b05 = 0.12 - 0.06 * n_sig + 0.01 * base   # red-edge 1 tracks N signal
        b07 = 0.18 - 0.08 * n_sig
        b8a = 0.30 + 0.28 * n_sig + 0.02 * base
        b12 = 0.20 - 0.10 * g
        b06 = 0.15 - 0.07 * n_sig
        bands = {k: v.astype("float32") for k, v in
                 dict(B02=b02, B04=b04, B05=b05, B06=b06, B07=b07, B08=b08, B8A=b8a, B12=b12).items()}
        scl = np.full((h, w), 4, dtype="uint8")  # vegetation
        cloud_pct = float(rng.uniform(2, 35))
        if rng.random() < 0.25:  # occasional cloud blob (SCL class 9)
            cy, cx = rng.integers(0, h), rng.integers(0, w)
            yy, xx = np.ogrid[:h, :w]
            blob = (yy - cy) ** 2 + (xx - cx) ** 2 < (h * 0.12) ** 2
            scl[blob] = 9
            for k in bands:
                bands[k] = np.where(blob, NODATA, bands[k])
        idx = compute_indices(bands)
        scene_dir = processed_root / "s2" / d.isoformat()
        band_list = [idx["ndvi"], idx["evi"], idx["ndre"], idx.get("ndre2", idx["ndre"]),
                     bands["B04"], bands["B08"], bands["B02"], scl.astype("float32")]
        band_names = ["ndvi", "evi", "ndre", "ndre2", "B04", "B08", "B02", "SCL"]
        cog = rio.write_cog(scene_dir / "scene.tif", band_list, transform,
                            crs="EPSG:4326", band_names=band_names)
        rio.quicklook_rgb(bands["B04"], bands["B08"], bands["B02"], scene_dir / "truecolor.png")
        rio.ndre_colormap(idx["ndre"], scene_dir / "ndre.png")
        record_scene_observations(
            scene_id=f"s2_{d.isoformat()}", source="s2", date=d.isoformat(),
            cloud_pct=cloud_pct, cog_path=str(cog.relative_to(config.PROCESSED_DIR)),
            quicklook_path=str((scene_dir / "ndre.png").relative_to(config.PROCESSED_DIR)),
            raster_path=cog, band_map={"ndvi": 1, "evi": 2, "ndre": 3, "ndre2": 4},
            source_label="s2",
        )
        n_scenes += 1
    return n_scenes


def generate_s1_mock(bbox: dict, months: int, processed_root: Path) -> int:
    """Monthly Sentinel-1 VH/VV backscatter (dB) per plot — the monsoon layer."""
    from .pipeline import ensure_series, write_plot_obs

    res = 0.0003  # ~30 m
    transform, w, h, labels, names = _plot_masks(bbox, res)
    dates = _monthly_dates(months)
    vh_series = ensure_series("s1_vh", "s1", "dB")
    vv_series = ensure_series("s1_vv", "s1", "dB")
    s1_plots = {pid for pid, n in names.items() if n in ANOMALY_S1}
    from .pipeline import scene_exists
    for d in dates:
        if scene_exists(f"s1_{d.isoformat()}"):
            continue
        wet = d.month in (6, 7, 8, 9)
        base_vh = -12.5 if wet else -16.5
        arr = np.full((h, w), base_vh + gaussian_filter(rng.normal(0, 0.4, (h, w)), 6), dtype="float32")
        for pid, name in names.items():
            m = labels == pid
            if m.any():
                v = float(arr[m].mean())
                if pid in s1_plots and wet:
                    v += 2.5  # standing water -> backscatter spike
                write_plot_obs(vh_series, pid, d.isoformat(), v)
                write_plot_obs(vv_series, pid, d.isoformat(), v - 6.0)
        scene_dir = processed_root / "s1" / d.isoformat()
        cog = rio.write_cog(scene_dir / "vh.tif", [arr], transform, crs="EPSG:4326",
                            nodata=NODATA, band_names=["s1_vh"])
        rio.quicklook_gray(arr, scene_dir / "vh.png", invert=True)
        with SessionLocal() as s:
            s.add(Scene(scene_id=f"s1_{d.isoformat()}", source="s1", date=d.isoformat(),
                        cloud_pct=None, cog_path=str(cog.relative_to(config.PROCESSED_DIR)),
                        quicklook_path=str((scene_dir / "vh.png").relative_to(config.PROCESSED_DIR)),
                        meta_json=json.dumps({"note": "monthly median GRD IW VV+VH"})))
            s.commit()
    return len(dates)


def generate_dem_canopy_mock(bbox: dict, processed_root: Path) -> dict:
    """Synthetic GLO-30-style DEM + GEDI-style canopy height, with per-plot stats."""
    from .pipeline import ensure_series, write_plot_obs

    res = 10 / 111320.0
    transform, w, h, labels, names = _plot_masks(bbox, res)
    yy, xx = np.mgrid[0:h, 0:w]
    dem = (820 + 60 * (yy / h) + 25 * (xx / w) + gaussian_filter(rng.normal(0, 3, (h, w)), 10)).astype("float32")
    slope = np.gradient(dem, res * 111320.0)
    slope_deg = np.degrees(np.arctan(np.hypot(slope[0], slope[1]))).astype("float32")
    canopy = np.clip(14 + 4 * np.sin(xx / w * np.pi) + gaussian_filter(rng.normal(0, 1.5, (h, w)), 6),
                     4, 25).astype("float32")

    dem_dir = processed_root / "dem" / "glo30"
    rio.write_cog(dem_dir / "dem.tif", [dem, slope_deg], transform, crs="EPSG:4326",
                  nodata=NODATA, band_names=["elevation_m", "slope_deg"])
    rio.quicklook_gray(dem, dem_dir / "hillshade.png")
    can_dir = processed_root / "canopy" / "gedi"
    rio.write_cog(can_dir / "canopy.tif", [canopy], transform, crs="EPSG:4326",
                  nodata=NODATA, band_names=["canopy_height_m"])
    rio.quicklook_gray(canopy, can_dir / "canopy.png")

    elev_s = ensure_series("elevation_m", "dem", "m")
    slope_s = ensure_series("slope_deg", "dem", "deg")
    can_s = ensure_series("canopy_height_m", "canopy", "m")
    with SessionLocal() as s:
        for p in s.query(Plot).filter(Plot.is_boundary == 0).all():
            gj = p.geom_geojson
            e = rio.zonal_mean(dem_dir / "dem.tif", gj, 1)
            sl = rio.zonal_mean(dem_dir / "dem.tif", gj, 2)
            ch = rio.zonal_mean(can_dir / "canopy.tif", gj, 1)
            ts = utcnow()
            if e is not None:
                write_plot_obs(elev_s, p.plot_id, ts, e)
            if sl is not None:
                write_plot_obs(slope_s, p.plot_id, ts, sl)
            if ch is not None:
                write_plot_obs(can_s, p.plot_id, ts, ch)
        scene_rows = [
            ("dem_glo30", "dem", "GLO-30 elevation/slope (mock)"),
            ("canopy_gedi", "canopy", "GEDI/Landsat canopy height (mock)"),
        ]
        for sid, src, note in scene_rows:
            s.add(Scene(scene_id=sid, source=src, date="2024-01-01", cloud_pct=None,
                        cog_path=str((dem_dir if src == "dem" else can_dir).relative_to(config.PROCESSED_DIR)),
                        quicklook_path=None, meta_json=json.dumps({"note": note})))
        s.commit()
    return {"dem": str(dem_dir), "canopy": str(can_dir)}
