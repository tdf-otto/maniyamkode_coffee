#!/usr/bin/env python3
"""Full first pull: S2 (36 months), S1 (monthly), DEM, canopy height, then
zonal stats + baselines + flags. Idempotent and resumable — scenes already in
the `scenes` table / on disk are skipped.

Usage:
  python scripts/preload.py            # live CDSE pull (needs .env credentials)
  python scripts/preload.py --mock     # synthetic rasters, no credentials (UI dev)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.db import init_db  # noqa: E402
from app.services.geo import derive_bbox, load_geojson, register_plots  # noqa: E402
from app.services.pipeline import register_default_sources, scene_exists, touch_source  # noqa: E402


def run_mock(months: int) -> None:
    from app.services import mockdata

    bbox = derive_bbox(load_geojson())
    register_plots()
    n_s2 = mockdata.generate_s2_mock(bbox, months, config.PROCESSED_DIR)
    print(f"[mock] wrote {n_s2} S2 scenes")
    n_s1 = mockdata.generate_s1_mock(bbox, months, config.PROCESSED_DIR)
    print(f"[mock] wrote {n_s1} S1 monthly composites")
    mockdata.generate_dem_canopy_mock(bbox, config.PROCESSED_DIR)
    print("[mock] wrote DEM + canopy rasters")
    touch_source("s2", "Sentinel-2 L2A (mock)", "ok")
    touch_source("s1", "Sentinel-1 GRD monthly (mock)", "ok")
    touch_source("dem", "GLO-30 DEM (mock)", "ok")
    touch_source("canopy", "GEDI/Landsat canopy height (mock)", "ok")


def run_live(months: int) -> None:
    """Live CDSE pull. Requires CDSE_CLIENT_ID/SECRET in .env.

    S2: STAC search for SENTINEL-2 L2A scenes < S2_MAX_CLOUD_PCT over the bbox,
    fetched server-side via openEO (clipped, cloud-masked COGs cached locally).
    S1: monthly medians. DEM: GLO-30 one-time. Canopy: GEDI/Landsat clip.
    """
    from app.services import cdse, pipeline
    from app.services.indices import compute_indices
    from app.services import raster as rio

    if not cdse.have_credentials():
        raise SystemExit("APP_MODE=live but CDSE_CLIENT_ID/SECRET missing — "
                         "copy .env.example to .env and fill in credentials, or use --mock.")
    bbox = derive_bbox(load_geojson())
    register_plots()
    auth = cdse.CDSEAuth()
    start = (date.today() - timedelta(days=30 * months)).isoformat()
    end = date.today().isoformat()

    # --- Sentinel-2 ---
    items = cdse.stac_search(auth, "SENTINEL-2 L2A", bbox, start, end,
                             max_cloud_pct=config.S2_MAX_CLOUD_PCT)
    print(f"[s2] {len(items)} scenes under {config.S2_MAX_CLOUD_PCT}% cloud since {start}")
    ok = 0
    for item in items:
        d = item["properties"]["datetime"][:10]
        scene_id = f"s2_{d}_{item['id'][:8]}"
        if scene_exists(scene_id):
            continue
        out_dir = config.PROCESSED_DIR / "s2" / d
        raw = cdse.fetch_s2_scene_live(auth, item, bbox, out_dir)
        if raw is None:
            continue
        # compute index bands from the downloaded bands, cache as processed COG
        with __import__("rasterio").open(raw) as src:
            bands = {name: src.read(i + 1).astype("float32") / 10000.0
                     for i, name in enumerate(src.descriptions)}
            transform, crs = src.transform, src.crs
        idx = compute_indices(bands)
        band_list = [idx.get("ndvi"), idx.get("evi"), idx.get("ndre"), idx.get("ndre2"),
                     bands.get("B04"), bands.get("B08"), bands.get("B02")]
        names = ["ndvi", "evi", "ndre", "ndre2", "B04", "B08", "B02"]
        keep = [(b, n) for b, n in zip(band_list, names) if b is not None]
        cog = rio.write_cog(out_dir / "scene.tif", [b for b, _ in keep], transform,
                            crs=str(crs), band_names=[n for _, n in keep])
        pipeline.record_scene_observations(
            scene_id=scene_id, source="s2", date=d,
            cloud_pct=item["properties"].get("eo:cloud_cover"),
            cog_path=str(cog.relative_to(config.PROCESSED_DIR)),
            quicklook_path=None, raster_path=cog,
            band_map={n: i + 1 for i, (_, n) in enumerate(keep)}, source_label="s2")
        ok += 1
    print(f"[s2] ingested {ok} new scenes")
    touch_source("s2", "Sentinel-2 L2A via CDSE STAC+openEO", "ok" if ok else "stale")

    # --- Sentinel-1 monthly medians (zonal, monsoon layer) ---
    # Implemented as monthly STAC search + per-plot zonal mean of VH; full
    # server-side median via openEO is a drop-in improvement (see hooks).
    s1_items = cdse.stac_search(auth, "SENTINEL1_GRD", bbox, start, end, max_cloud_pct=None)
    print(f"[s1] {len(s1_items)} GRD scenes found; monthly medians per plot")
    from collections import defaultdict
    by_month: dict[str, list] = defaultdict(list)
    for it in s1_items:
        by_month[it["properties"]["datetime"][:7]].append(it)
    vh = pipeline.ensure_series("s1_vh", "s1", "dB")
    vv = pipeline.ensure_series("s1_vv", "s1", "dB")
    for month, its in sorted(by_month.items()):
        # one representative scene per month is enough for the continuity layer
        it = its[0]
        out_dir = config.PROCESSED_DIR / "s1" / month
        if scene_exists(f"s1_{month}"):
            continue
        # download VH/VV via openeo clip (polarization VV+VH, IW)
        graph = {
            "load": {"process_id": "load_collection",
                     "arguments": {"id": "SENTINEL1_GRD",
                                   "spatial_extent": {"west": bbox["west"], "south": bbox["south"],
                                                      "east": bbox["east"], "north": bbox["north"]},
                                   "temporal_extent": [f"{month}-01T00:00:00Z",
                                                       f"{month}-28T23:59:59Z"],
                                   "bands": ["VV", "VH"]},
                     "result": True},
        }
        try:
            tif = cdse.openeo_download_cog(graph, out_dir / "grd.tif", auth)
        except cdse.CDSEError as e:
            print(f"[s1] {month} failed: {e}")
            continue
        import numpy as np
        import rasterio
        from app.db import SessionLocal
        from app.db.models import Plot
        with rasterio.open(tif) as src:
            bands = {src.descriptions[i]: src.read(i + 1) for i in range(src.count)}
        with SessionLocal() as s:
            for p in s.query(Plot).filter(Plot.is_boundary == 0).all():
                for var, arr in (("s1_vh", bands.get("VH")), ("s1_vv", bands.get("VV"))):
                    if arr is None:
                        continue
                    tmp = out_dir / f"_{var}.tif"
                    rio.write_cog(tmp, [arr.astype("float32")], src.transform, crs=str(src.crs))
                    v = rio.zonal_mean(tmp, p.geom_geojson, 1)
                    tmp.unlink(missing_ok=True)
                    if v is not None:
                        pipeline.write_plot_obs(vh if var == "s1_vh" else vv, p.plot_id,
                                                f"{month}-15", float(v))
        pipeline.touch_source("s1", "Sentinel-1 GRD monthly VH/VV via CDSE", "ok")

    # --- DEM (GLO-30) one-time ---
    if not scene_exists("dem_glo30"):
        dem = cdse.fetch_glo30_dem(auth, bbox, config.CACHE_DIR)
        # clip + zonal stats happen in services.raster via processed copy
        out_dir = config.PROCESSED_DIR / "dem" / "glo30"
        out_dir.mkdir(parents=True, exist_ok=True)
        import rasterio
        from rasterio.mask import mask as rio_mask
        from shapely.geometry import shape
        from app.services.geo import bbox_geojson
        with rasterio.open(dem) as src:
            out, tr = rio_mask(src, [shape(__import__("json").loads(bbox_geojson(bbox)))],
                               crop=True)
            profile = src.profile.copy()
            profile.update(height=out.shape[1], width=out.shape[2], transform=tr)
            cog = out_dir / "dem.tif"
            with rasterio.open(cog, "w", **profile) as dst:
                dst.write(out)
        rio.quicklook_gray(out[0], out_dir / "hillshade.png")
        from app.db import SessionLocal, utcnow
        from app.db.models import Scene, Plot
        elev = pipeline.ensure_series("elevation_m", "dem", "m")
        slope_s = pipeline.ensure_series("slope_deg", "dem", "deg")
        import numpy as np
        gy, gx = np.gradient(out[0].astype("float32"), 30.0)
        slope_arr = np.degrees(np.arctan(np.hypot(gx, gy)))
        slope_cog = out_dir / "slope.tif"
        rio.write_cog(slope_cog, [slope_arr], tr, crs=str(src.crs), band_names=["slope_deg"])
        with SessionLocal() as s:
            for p in s.query(Plot).filter(Plot.is_boundary == 0).all():
                e = rio.zonal_mean(cog, p.geom_geojson, 1)
                sl = rio.zonal_mean(slope_cog, p.geom_geojson, 1)
                ts = utcnow()
                if e is not None:
                    pipeline.write_plot_obs(elev, p.plot_id, ts, e)
                if sl is not None:
                    pipeline.write_plot_obs(slope_s, p.plot_id, ts, sl)
            s.add(Scene(scene_id="dem_glo30", source="dem", date=start, cloud_pct=None,
                        cog_path=str(cog.relative_to(config.PROCESSED_DIR)),
                        quicklook_path=str((out_dir / "hillshade.png").relative_to(config.PROCESSED_DIR)),
                        meta_json='{"product": "COP-DEM GLO-30"}'))
            s.commit()
        touch_source("dem", "Copernicus GLO-30 DEM", "ok")
        print("[dem] GLO-30 clipped and ingested")
    else:
        print("[dem] already cached, skipped")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="synthetic rasters, no CDSE needed")
    ap.add_argument("--months", type=int, default=config.PRELOAD_MONTHS)
    args = ap.parse_args()

    config.ensure_dirs()
    init_db()
    register_default_sources()
    if args.mock or config.APP_MODE == "mock":
        print("== preload (MOCK mode) ==")
        run_mock(args.months)
    else:
        print("== preload (LIVE CDSE mode) ==")
        run_live(args.months)

    # analysis pass: baselines, flags, breakpoints
    from scripts.analyze import run_analysis
    run_analysis()
    print("preload complete")


if __name__ == "__main__":
    main()
