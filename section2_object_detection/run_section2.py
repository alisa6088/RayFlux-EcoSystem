"""
section2_object_detection/run_section2.py
Master standalone orchestrator for Section 2: Rooftop Object Detection Engine (V3 Multi-Modal CV, No Parallax).

Pipeline:
  1. Loads 3D building footprints (`public.s01_building_footprints`) from PostGIS (or GPKG/SHP fallback).
  2. Loads tuned V3 CV hyperparameters from `config/cv_hyperparameters.yaml`.
  3. Runs multi-process V3 multi-modal CV across all buildings (NDCI + 4-Dir GLCM + Gabor +
     Top-Hat/Black-Hat + Shadow Disambiguation + OBIA Vectorization + Boolean Roof Subtraction).
  4. Commits `s02_usable_rooftops`, `s02_physical_obstacles`, and `s02_cast_shadows` to PostGIS,
     Master GeoPackage, standardized ESRI Shapefiles, and a single Excel report (`.xlsx`).
  5. Generates 4-panel per-building diagnostic cards and the full-scene overview map.
"""
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

import geopandas as gpd
import numpy as np
from shapely import wkb

from config.ecosystem_config import EcosystemConfig, to_project_relative_posix
from core_db.database_manager import CentralDatabaseManager
from section2_object_detection.cv_config import CVHyperparameters
from section2_object_detection.vectorizer_topology import (
    ObstacleVectorizer,
    OrthoWindowCropper,
    RooftopSpatialEngine,
)
from section2_object_detection.vision_models.unified_detector import UnifiedRooftopDetector
from section2_object_detection.visualizer import (
    render_roof_diagnostic_card,
    render_scene_detection_map,
)


def _process_building_chunk(
    chunk_items: List[Tuple[int, bytes]],
    ortho_tif_str: str,
    yaml_path_str: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Worker function: processes a batch of `(building_id, wkb_bytes)` using its own rasterio handle."""
    initialize_spatial_env()
    params = CVHyperparameters.load_yaml(Path(yaml_path_str))
    cropper = OrthoWindowCropper(Path(ortho_tif_str), pad_meters=params.cropping.pad_meters)
    detector = UnifiedRooftopDetector(params)
    vectorizer = ObstacleVectorizer(params)
    spatial_engine = RooftopSpatialEngine(min_usable_patch_m2=params.usable_area.min_usable_patch_area_m2)

    usable_rows: List[Dict[str, Any]] = []
    obstacle_rows: List[Dict[str, Any]] = []
    shadow_rows: List[Dict[str, Any]] = []

    try:
        for bldg_id, geom_wkb in chunk_items:
            geom = wkb.loads(geom_wkb)
            rgb_img, win_transform = cropper.crop_building(geom)
            det_res = detector.process_roof(rgb_img, geom, win_transform)

            obs_items = vectorizer.vectorize_obstacles(det_res["physical_objects_mask"], win_transform, bldg_id)
            shd_items = vectorizer.vectorize_shadows(det_res["shadows_mask"], win_transform, bldg_id)

            obs_geoms = [o["geometry"] for o in obs_items]
            shd_geoms = [s["geometry"] for s in shd_items]

            net_geom, metrics = spatial_engine.subtract_physical_objects(geom, obs_geoms, shd_geoms)

            cooler_cnt = sum(1 for o in obs_items if o["obj_class"] == "COOLER_AC")
            penthouse_cnt = sum(1 for o in obs_items if o["obj_class"] == "PENTHOUSE")
            vent_cnt = sum(1 for o in obs_items if o["obj_class"] == "CHIMNEY_VENT")

            usable_rows.append({
                "building_id": int(bldg_id),
                "gross_area_m2": metrics["orig_area"],
                "obstacle_area_m2": metrics["obj_area"],
                "cast_shadow_area_m2": metrics["shd_area"],
                "usable_area_m2": metrics["net_area"],
                "usable_area_pct": metrics["usable_pct"],
                "obstacle_count": metrics["obj_cnt"],
                "cooler_ac_count": cooler_cnt,
                "penthouse_count": penthouse_cnt,
                "chimney_vent_count": vent_cnt,
                "suitability_status": metrics["status"],
                "geometry_wkb": wkb.dumps(net_geom),
            })

            for o in obs_items:
                obstacle_rows.append({
                    "building_id": o["building_id"],
                    "obj_class": o["obj_class"],
                    "area_m2": o["area_m2"],
                    "conf": o["conf"],
                    "geometry_wkb": wkb.dumps(o["geometry"]),
                })

            for s in shd_items:
                shadow_rows.append({
                    "building_id": s["building_id"],
                    "obj_class": s["obj_class"],
                    "area_m2": s["area_m2"],
                    "geometry_wkb": wkb.dumps(s["geometry"]),
                })
    finally:
        cropper.close()

    return usable_rows, obstacle_rows, shadow_rows


def _select_sample_buildings(usable_gdf: gpd.GeoDataFrame, max_cards: int = 8) -> List[int]:
    """Selects a diverse set of representative buildings (largest + mid-sized with obstacles) for diagnostic cards."""
    if usable_gdf.empty:
        return []
    df = usable_gdf.copy()
    has_obs = df[df["obstacle_count"] > 0]
    chosen: List[int] = []

    if not has_obs.empty:
        # Top 4 largest roofs with obstacles
        for bid in has_obs.sort_values("gross_area_m2", ascending=False)["building_id"].head(4).tolist():
            if bid not in chosen:
                chosen.append(int(bid))
        # Top 2 highest obstacle-count roofs
        for bid in has_obs.sort_values("obstacle_count", ascending=False)["building_id"].head(2).tolist():
            if bid not in chosen:
                chosen.append(int(bid))
        # 2 medium-sized roofs (around 75th percentile area) with obstacles
        med_area = float(has_obs["gross_area_m2"].quantile(0.75))
        near_med = has_obs.iloc[(has_obs["gross_area_m2"] - med_area).abs().argsort()[:4]]
        for bid in near_med["building_id"].tolist():
            if bid not in chosen and len(chosen) < max_cards:
                chosen.append(int(bid))

    if len(chosen) < max_cards:
        for bid in df.sort_values("gross_area_m2", ascending=False)["building_id"].tolist():
            if bid not in chosen:
                chosen.append(int(bid))
            if len(chosen) >= max_cards:
                break

    return chosen[:max_cards]


def run_section2(
    config: EcosystemConfig = None,
    max_workers: int = None,
    num_diagnostic_cards: int = 8,
) -> Dict[str, Any]:
    t0 = time.time()
    cfg = config or EcosystemConfig()
    cfg.db.ensure_directories()
    db_mgr = CentralDatabaseManager(cfg)

    print("=" * 72)
    print("  RAYFLUX ECOSYSTEM — SECTION 2: ROOFTOP OBJECT DETECTION (V3 CV)")
    print("=" * 72)

    # 1. Load inputs from Central Database (PostGIS primary)
    print("[S2] Loading s01_building_footprints from Central Database...")
    bldgs_gdf = db_mgr.load_vector_dataset(cfg.db.s01_footprints_shp, gpkg_layer="s01_building_footprints")
    target_crs = cfg.target_crs or str(bldgs_gdf.crs)
    if not cfg.db.s01_ortho_tif.exists():
        raise FileNotFoundError(f"Missing Section 1 orthophoto: {to_project_relative_posix(cfg.db.s01_ortho_tif)}")

    params = CVHyperparameters.load_yaml(cfg.cv_hyperparams_yaml)
    print(f"[S2] Loaded {len(bldgs_gdf):,} buildings (CRS={target_crs}).")
    print(f"[S2] Hyperparameters loaded from: {to_project_relative_posix(cfg.cv_hyperparams_yaml)}")

    # 2. Prepare parallel batches
    items = [(int(row.building_id), wkb.dumps(row.geometry)) for row in bldgs_gdf.itertuples(index=False)]
    n_workers = max_workers or max(1, min(os.cpu_count() or 4, 8))
    chunk_size = max(1, (len(items) + (n_workers * 4) - 1) // (n_workers * 4))
    chunks = [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]

    print(f"[S2] Running V3 multi-modal CV across {len(items):,} buildings ({n_workers} workers, {len(chunks)} chunks)...")

    all_usable: List[Dict[str, Any]] = []
    all_obstacles: List[Dict[str, Any]] = []
    all_shadows: List[Dict[str, Any]] = []

    completed = 0
    if n_workers == 1 or len(chunks) == 1:
        for ch in chunks:
            u, o, s = _process_building_chunk(ch, str(cfg.db.s01_ortho_tif), str(cfg.cv_hyperparams_yaml))
            all_usable.extend(u)
            all_obstacles.extend(o)
            all_shadows.extend(s)
            completed += len(ch)
            print(f"     -> Processed {completed:,}/{len(items):,} buildings ({completed / len(items) * 100:.1f}%)")
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_process_building_chunk, ch, str(cfg.db.s01_ortho_tif), str(cfg.cv_hyperparams_yaml)): len(ch)
                for ch in chunks
            }
            for fut in as_completed(futures):
                u, o, s = fut.result()
                all_usable.extend(u)
                all_obstacles.extend(o)
                all_shadows.extend(s)
                completed += futures[fut]
                if completed % max(1, len(items) // 8) < chunk_size or completed == len(items):
                    print(f"     -> Processed {completed:,}/{len(items):,} buildings ({completed / len(items) * 100:.1f}%)")

    # 3. Reconstruct GeoDataFrames
    for row in all_usable:
        row["geometry"] = wkb.loads(row.pop("geometry_wkb"))
    for row in all_obstacles:
        row["geometry"] = wkb.loads(row.pop("geometry_wkb"))
    for row in all_shadows:
        row["geometry"] = wkb.loads(row.pop("geometry_wkb"))

    usable_gdf = gpd.GeoDataFrame(all_usable, geometry="geometry", crs=target_crs)
    usable_gdf = usable_gdf.sort_values("building_id").reset_index(drop=True)

    if all_obstacles:
        obstacles_gdf = gpd.GeoDataFrame(all_obstacles, geometry="geometry", crs=target_crs)
        obstacles_gdf = obstacles_gdf.sort_values(["building_id", "area_m2"], ascending=[True, False]).reset_index(drop=True)
    else:
        obstacles_gdf = gpd.GeoDataFrame(
            columns=["building_id", "obj_class", "area_m2", "conf", "geometry"],
            geometry="geometry",
            crs=target_crs,
        )

    if all_shadows:
        shadows_gdf = gpd.GeoDataFrame(all_shadows, geometry="geometry", crs=target_crs)
        shadows_gdf = shadows_gdf.sort_values(["building_id", "area_m2"], ascending=[True, False]).reset_index(drop=True)
    else:
        shadows_gdf = gpd.GeoDataFrame(
            columns=["building_id", "obj_class", "area_m2", "geometry"],
            geometry="geometry",
            crs=target_crs,
        )

    # 4. Commit outputs to Central Database (PostGIS + GPKG + Shapefile + single Excel .xlsx)
    print("[S2] Committing s02_usable_rooftops to PostGIS, GPKG, Shapefile, and Excel (.xlsx)...")
    db_mgr.save_vector_dataset(
        gdf=usable_gdf,
        shp_path=cfg.db.s02_usable_rooftops_shp,
        gpkg_layer="s02_usable_rooftops",
        excel_path=cfg.db.s02_usable_report_xlsx,
    )

    print(f"[S2] Committing s02_physical_obstacles ({len(obstacles_gdf):,} polygons)...")
    if not obstacles_gdf.empty:
        db_mgr.save_vector_dataset(
            gdf=obstacles_gdf,
            shp_path=cfg.db.s02_obstacles_shp,
            gpkg_layer="s02_physical_obstacles",
            excel_path=None,
        )

    print(f"[S2] Committing s02_cast_shadows ({len(shadows_gdf):,} polygons)...")
    if not shadows_gdf.empty:
        db_mgr.save_vector_dataset(
            gdf=shadows_gdf,
            shp_path=cfg.db.s02_shadows_shp,
            gpkg_layer="s02_cast_shadows",
            excel_path=None,
        )

    # 5. Render sample 4-panel diagnostic cards
    sample_ids = _select_sample_buildings(usable_gdf, max_cards=num_diagnostic_cards)
    print(f"[S2] Rendering {len(sample_ids)} sample 4-panel diagnostic cards: {sample_ids}")
    cropper = OrthoWindowCropper(cfg.db.s01_ortho_tif, pad_meters=params.cropping.pad_meters)
    detector = UnifiedRooftopDetector(params)
    gross_lookup = dict(zip(bldgs_gdf["building_id"].astype(int), bldgs_gdf.geometry))
    usable_lookup = usable_gdf.set_index("building_id")
    card_paths: List[str] = []
    try:
        for bid in sample_ids:
            gross_geom = gross_lookup[bid]
            u_row = usable_lookup.loc[bid]
            rgb_img, win_transform = cropper.crop_building(gross_geom)
            det_res = detector.process_roof(rgb_img, gross_geom, win_transform)
            metrics = {
                "orig_area": float(u_row["gross_area_m2"]),
                "obj_area": float(u_row["obstacle_area_m2"]),
                "shd_area": float(u_row["cast_shadow_area_m2"]),
                "net_area": float(u_row["usable_area_m2"]),
                "usable_pct": float(u_row["usable_area_pct"]),
                "obj_cnt": int(u_row["obstacle_count"]),
                "status": str(u_row["suitability_status"]),
            }
            out_card = cfg.db.roof_diag_card_png(bid)
            render_roof_diagnostic_card(
                building_id=bid,
                rgb_img=rgb_img,
                win_transform=win_transform,
                gross_geom=gross_geom,
                net_geom=u_row.geometry,
                det_res=det_res,
                metrics=metrics,
                out_png=out_card,
            )
            card_paths.append(to_project_relative_posix(out_card))
    finally:
        cropper.close()

    # 6. Render full-scene detection overview map
    print("[S2] Rendering full-scene detection overview map...")
    render_scene_detection_map(
        ortho_tif_path=cfg.db.s01_ortho_tif,
        usable_gdf=usable_gdf,
        obstacles_gdf=obstacles_gdf,
        shadows_gdf=shadows_gdf,
        out_png=cfg.db.s02_scene_map_png,
    )

    # 7. Automated QA Self-Audit (area conservation + outlier check)
    area_err = np.abs((usable_gdf["usable_area_m2"] + usable_gdf["obstacle_area_m2"]) - usable_gdf["gross_area_m2"])
    max_area_err = float(area_err.max()) if not usable_gdf.empty else 0.0
    low_usable_cnt = int((usable_gdf["usable_area_pct"] < 30.0).sum()) if not usable_gdf.empty else 0

    elapsed = time.time() - t0
    total_gross = float(usable_gdf["gross_area_m2"].sum())
    total_usable = float(usable_gdf["usable_area_m2"].sum())
    total_obs_area = float(usable_gdf["obstacle_area_m2"].sum())
    total_shd_area = float(usable_gdf["cast_shadow_area_m2"].sum())
    usable_pct = (total_usable / total_gross * 100.0) if total_gross > 0 else 0.0

    status_counts = usable_gdf["suitability_status"].value_counts().to_dict()
    class_counts = obstacles_gdf["obj_class"].value_counts().to_dict() if not obstacles_gdf.empty else {}

    print("=" * 72)
    print(f"  SECTION 2 COMPLETE in {elapsed:.1f}s")
    print(f"  Buildings Processed : {len(usable_gdf):,}")
    print(f"  Total Gross Area    : {total_gross:,.1f} m² ({total_gross / 1e4:.2f} ha)")
    print(f"  Physical Obstacles  : {len(obstacles_gdf):,} polygons ({total_obs_area:,.1f} m²) {class_counts}")
    print(f"  Cast Shadows        : {len(shadows_gdf):,} polygons ({total_shd_area:,.1f} m²) [Retained]")
    print(f"  Net Usable Area     : {total_usable:,.1f} m² ({usable_pct:.1f}%)")
    print(f"  Suitability Breakdown: {status_counts}")
    print(f"  QA Audit            : max_area_err={max_area_err:.3f} m² | low_usable(<30%)={low_usable_cnt}")
    print(f"  Excel Report        : {to_project_relative_posix(cfg.db.s02_usable_report_xlsx)}")
    print(f"  Scene Map           : {to_project_relative_posix(cfg.db.s02_scene_map_png)}")
    print("=" * 72)

    return {
        "buildings_processed": len(usable_gdf),
        "obstacles_count": len(obstacles_gdf),
        "shadows_count": len(shadows_gdf),
        "total_gross_m2": round(total_gross, 2),
        "total_usable_m2": round(total_usable, 2),
        "usable_pct": round(usable_pct, 2),
        "status_counts": status_counts,
        "class_counts": class_counts,
        "diagnostic_cards": card_paths,
        "elapsed_sec": round(elapsed, 2),
    }


if __name__ == "__main__":
    run_section2()
