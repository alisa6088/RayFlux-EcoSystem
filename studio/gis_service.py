"""
studio/gis_service.py
GIS Vector GeoJSON Serving, On-The-Fly GeoTIFF-to-PNG WGS84 Map Overlays,
Full Data Inventory Explorer, Table Preview, ZIP Shapefile Export, and Safe Asset Deletion.
"""
import base64
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import zipfile

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.cm as cm
import numpy as np
import pandas as pd
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
from sqlalchemy import text

from config.ecosystem_config import EcosystemConfig, PROJECT_ROOT, to_project_relative_posix
from core_db.database_manager import CentralDatabaseManager
from studio.area_registry import area_registry
from studio.smart_logger import studio_logger


LAYER_MAP = {
    "footprints": ("s01_building_footprints", "s01_footprints_shp"),
    "usable_rooftops": ("s02_usable_rooftops", "s02_usable_rooftops_shp"),
    "obstacles": ("s02_physical_obstacles", "s02_obstacles_shp"),
    "shadows": ("s02_cast_shadows", "s02_shadows_shp"),
    "zonal_stats": ("s03_solar_zonal_stats", "s03_zonal_stats_shp"),
    "hotspots": ("s03_solar_hotspots_final", "s03_hotspots_final_shp"),
}

RASTER_KEYS = {
    "ortho_rgb": ("s01_ortho_tif", "RGB Orthophoto (Section 1)", "rgb"),
    "synthetic_dsm": ("s01_synthetic_dsm_tif", "3D Synthetic DSM (Section 1)", "viridis"),
    "irradiance_annual": ("s03_annual_rad_tif", "Annual Solar Irradiance (kWh/m²/yr)", "inferno"),
    "sky_view_factor": ("s03_svf_tif", "Sky View Factor (SVF 0–1)", "cividis"),
    "shadow_fraction": ("s03_shadow_frac_tif", "Daytime Shadow Fraction (%)", "magma"),
    "suitability_mask": ("s03_suitability_tif", "Radiation Suitability Mask", "Greens"),
}


def get_all_area_boundaries_geojson() -> Dict[str, Any]:
    """Returns a WGS84 GeoJSON FeatureCollection of all registered study area boundaries."""
    features: List[Dict[str, Any]] = []
    for area in area_registry.list_areas():
        aoi_path = PROJECT_ROOT / area["aoi_path"]
        if not aoi_path.exists():
            continue
        try:
            gdf = gpd.read_file(aoi_path)
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            gdf_wgs = gdf.to_crs("EPSG:4326")
            geom_union = gdf_wgs.geometry.unary_union
            if not geom_union.is_empty:
                geom_union = geom_union.simplify(0.0001, preserve_topology=True)
            features.append({
                "type": "Feature",
                "properties": {
                    "area_id": area["area_id"],
                    "name": area["name"],
                    "area_types": ", ".join(area.get("area_types", [])),
                    "area_km2": area.get("area_km2", 0.0),
                    "target_crs": area.get("target_crs", ""),
                    "buildings_count": area["section_status"]["buildings_count"],
                    "s1": area["section_status"]["section1"],
                    "s2": area["section_status"]["section2"],
                    "s3": area["section_status"]["section3"],
                },
                "geometry": json.loads(gpd.GeoSeries([geom_union]).to_json())["features"][0]["geometry"],
            })
        except Exception as exc:
            studio_logger.warning(f"Failed loading boundary for {area['area_id']}: {exc}", section="GIS")
    return {"type": "FeatureCollection", "features": features}


def get_area_vector_geojson(
    area_id: str,
    layer_key: str,
    simplify_m: float = 0.4,
    max_features: int = 8000,
) -> Dict[str, Any]:
    """Returns a fast WGS84 GeoJSON FeatureCollection for a vector layer of an area."""
    if layer_key not in LAYER_MAP:
        raise ValueError(f"Unknown layer '{layer_key}'. Valid: {list(LAYER_MAP.keys())}")
    gpkg_layer, shp_attr = LAYER_MAP[layer_key]
    cfg = area_registry.build_ecosystem_config(area_id)

    gdf = None
    if cfg.db.master_gpkg.exists():
        try:
            gdf = gpd.read_file(cfg.db.master_gpkg, layer=gpkg_layer)
        except Exception:
            gdf = None
    if gdf is None:
        shp_path = getattr(cfg.db, shp_attr)
        if shp_path.exists():
            gdf = gpd.read_file(shp_path)
    if gdf is None or gdf.empty:
        return {"type": "FeatureCollection", "features": [], "layer": layer_key, "count": 0}

    # Keep only concise popup attributes for crisp browser rendering speed
    keep_cols = [
        c for c in [
            "building_id", "gross_area_m2", "building_height_m", "num_floors",
            "usable_area_m2", "usable_area_pct", "obstacle_area_m2", "obstacle_count",
            "cast_shadow_area_m2", "suitability_status", "obj_class", "area_m2", "conf",
            "mean_kwh_m2_yr", "mean_svf", "mean_shadow_pct", "installed_capacity_kwp",
            "elec_yield_mwh_yr", "gi_z_score", "gi_p_value", "gi_cluster_class",
        ]
        if c in gdf.columns
    ]

    if len(gdf) > max_features:
        sort_col = "area_m2" if "area_m2" in gdf.columns else ("elec_yield_mwh_yr" if "elec_yield_mwh_yr" in gdf.columns else None)
        if sort_col:
            gdf = gdf.nlargest(max_features, sort_col).copy()
        else:
            gdf = gdf.head(max_features).copy()

    gdf = gdf[keep_cols + ["geometry"]].copy()
    if simplify_m > 0 and gdf.crs and gdf.crs.is_projected:
        gdf["geometry"] = gdf.geometry.simplify(simplify_m, preserve_topology=True)
    gdf_wgs = gdf.to_crs("EPSG:4326")

    # Replace NaN/inf with None for valid JSON
    for col in keep_cols:
        if pd.api.types.is_numeric_dtype(gdf_wgs[col]):
            gdf_wgs[col] = gdf_wgs[col].replace([np.inf, -np.inf], np.nan).where(gdf_wgs[col].notna(), None)

    fc = json.loads(gdf_wgs.to_json(drop_id=True))
    fc["layer"] = layer_key
    fc["count"] = len(fc.get("features", []))
    return fc


def render_raster_overlay_png(area_id: str, raster_key: str, max_dim: int = 1200) -> Dict[str, Any]:
    """Reprojects/downsamples a GeoTIFF to an EPSG:4326 RGBA PNG (base64 data URI) + Leaflet bounds."""
    cfg = area_registry.build_ecosystem_config(area_id)

    if raster_key in RASTER_KEYS:
        attr, label, cmap_name = RASTER_KEYS[raster_key]
        tif_path = getattr(cfg.db, attr)
    elif raster_key.startswith("monthly_m"):
        m_num = int(raster_key.replace("monthly_m", ""))
        tif_path = cfg.db.monthly_rad_tif(m_num)
        label = f"Monthly Irradiance Month {m_num:02d} (kWh/m²)"
        cmap_name = "inferno"
    else:
        raise ValueError(f"Unknown raster key '{raster_key}'.")

    if not tif_path.exists():
        raise FileNotFoundError(f"Raster not found for area '{area_id}': {to_project_relative_posix(tif_path)}")

    with rasterio.open(tif_path) as src:
        dst_crs = "EPSG:4326"
        transform, w, h = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)
        scale = min(1.0, max_dim / max(w, h))
        out_w = max(1, int(round(w * scale)))
        out_h = max(1, int(round(h * scale)))
        # Scale transform for target dimensions
        adj_transform = rasterio.transform.from_bounds(
            *rasterio.warp.transform_bounds(src.crs, dst_crs, *src.bounds),
            width=out_w,
            height=out_h,
        )
        west, south, east, north = rasterio.warp.transform_bounds(src.crs, dst_crs, *src.bounds)

        if cmap_name == "rgb" and src.count >= 3:
            dst = np.zeros((3, out_h, out_w), dtype=np.uint8)
            for b in range(1, 4):
                reproject(
                    source=rasterio.band(src, b),
                    destination=dst[b - 1],
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=adj_transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                )
            alpha = np.where((dst[0] == 0) & (dst[1] == 0) & (dst[2] == 0), 0, 255).astype(np.uint8)
            rgba = np.dstack([dst[0], dst[1], dst[2], alpha])
            vmin, vmax = 0.0, 255.0
        else:
            nodata_val = src.nodata if src.nodata is not None else -9999.0
            dst = np.full((out_h, out_w), np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=dst,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=nodata_val,
                dst_transform=adj_transform,
                dst_crs=dst_crs,
                dst_nodata=np.nan,
                resampling=Resampling.nearest,
            )
            valid = np.isfinite(dst) & (dst > -9000.0)
            if raster_key == "synthetic_dsm":
                valid = valid & (dst > 0.1)
            vals = dst[valid]
            if vals.size == 0:
                vmin, vmax = 0.0, 1.0
            else:
                vmin = float(np.percentile(vals, 2))
                vmax = float(np.percentile(vals, 99))
                if vmax <= vmin:
                    vmax = vmin + 1.0
            norm = np.clip((dst - vmin) / (vmax - vmin), 0.0, 1.0)
            norm[~valid] = 0.0
            cmap = cm.get_cmap(cmap_name)
            rgba_f = cmap(norm)
            rgba = (rgba_f * 255).astype(np.uint8)
            rgba[~valid, 3] = 0

    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "raster_key": raster_key,
        "label": label,
        "bounds": [[south, west], [north, east]],
        "vmin": round(vmin, 2),
        "vmax": round(vmax, 2),
        "data_url": f"data:image/png;base64,{b64}",
    }


def get_area_data_inventory(area_id: str) -> Dict[str, Any]:
    """Lists every asset (PostGIS tables, GeoTIFFs, Shapefiles, GPKG, Excel, PNG maps & cards) for an area."""
    area = area_registry.get_area(area_id)
    cfg = area_registry.build_ecosystem_config(area_id)
    db_root = PROJECT_ROOT / area["db_root"]

    def _file_info(p: Path, kind: str, section: str, map_key: Optional[str] = None) -> Dict[str, Any]:
        return {
            "name": p.name,
            "rel_path": to_project_relative_posix(p),
            "kind": kind,
            "section": section,
            "size_mb": round(p.stat().st_size / (1024 * 1024), 3),
            "map_key": map_key,
            "is_image": p.suffix.lower() in (".png", ".jpg", ".jpeg"),
        }

    rasters, shapefiles, tables, maps, cards, gpkgs = [], [], [], [], [], []

    # Check standard GeoTIFFs
    for rkey, (attr, label, _) in RASTER_KEYS.items():
        p = getattr(cfg.db, attr)
        if p.exists():
            info = _file_info(p, "raster", "S1" if rkey in ("ortho_rgb", "synthetic_dsm") else "S3", map_key=rkey)
            info["label"] = label
            rasters.append(info)
    if cfg.db.s03_horizon_tif.exists():
        info = _file_info(cfg.db.s03_horizon_tif, "raster", "S3", map_key=None)
        info["label"] = "32-Direction Horizon Angles (32 bands)"
        rasters.append(info)
    for m in range(1, 13):
        mp = cfg.db.monthly_rad_tif(m)
        if mp.exists():
            info = _file_info(mp, "raster", "S3", map_key=f"monthly_m{m:02d}")
            info["label"] = f"Monthly Irradiance M{m:02d}"
            rasters.append(info)

    # Shapefiles
    for lkey, (gpkg_lyr, shp_attr) in LAYER_MAP.items():
        p = getattr(cfg.db, shp_attr)
        if p.exists():
            sec = "S1" if gpkg_lyr.startswith("s01") else ("S2" if gpkg_lyr.startswith("s02") else "S3")
            info = _file_info(p, "shapefile", sec, map_key=lkey)
            info["layer"] = gpkg_lyr
            shapefiles.append(info)

    # Master GPKG
    if cfg.db.master_gpkg.exists():
        gpkgs.append(_file_info(cfg.db.master_gpkg, "geopackage", "CORE"))

    # Tables (.xlsx / .csv)
    tables_dir = db_root / "tables"
    if tables_dir.exists():
        for p in sorted(tables_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in (".xlsx", ".csv"):
                sec = "S1" if "s01" in p.name else ("S2" if "s02" in p.name else "S3")
                tables.append(_file_info(p, "table", sec))

    # Maps & Cards
    maps_dir = db_root / "maps"
    if maps_dir.exists():
        for p in sorted(maps_dir.rglob("*.png")):
            sec = "S1" if "s01" in p.name else ("S2" if "s02" in p.name else "S3")
            if "cards" in p.parts:
                cards.append(_file_info(p, "card", sec))
            else:
                maps.append(_file_info(p, "map", sec))

    # PostGIS live table inspection
    pg_tables = []
    pg_online = False
    schema = area.get("postgis_schema", "public")
    try:
        eng = CentralDatabaseManager(cfg).get_postgis_engine()
        if eng is not None:
            pg_online = True
            with eng.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_name LIKE 's0%' ORDER BY table_name"
                    ),
                    {"schema": schema},
                ).fetchall()
                for (tname,) in rows:
                    cnt = conn.execute(text(f'SELECT COUNT(*) FROM "{schema}"."{tname}"')).scalar()
                    sz = conn.execute(text(f"SELECT pg_size_pretty(pg_total_relation_size('\"{schema}\".\"{tname}\"'))")).scalar()
                    pg_tables.append({
                        "schema": schema,
                        "table": tname,
                        "rows": int(cnt or 0),
                        "size": str(sz or ""),
                    })
    except Exception:
        pg_online = False

    return {
        "area_id": area_id,
        "postgis_online": pg_online,
        "postgis_schema": schema,
        "postgis_tables": pg_tables,
        "rasters": rasters,
        "shapefiles": shapefiles,
        "geopackages": gpkgs,
        "tables": tables,
        "maps": maps,
        "cards": cards,
    }


def preview_table_rows(area_id: str, layer_name: str, limit: int = 80) -> Dict[str, Any]:
    """Returns the first N non-geometry rows of a layer from PostGIS or GeoPackage."""
    cfg = area_registry.build_ecosystem_config(area_id)
    gdf = None
    if cfg.db.master_gpkg.exists():
        try:
            gdf = gpd.read_file(cfg.db.master_gpkg, layer=layer_name, rows=limit)
        except Exception:
            gdf = None
    if gdf is None:
        raise FileNotFoundError(f"Layer '{layer_name}' not found for area '{area_id}'.")

    df = pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))
    df = df.replace([np.inf, -np.inf], np.nan)
    records = json.loads(df.to_json(orient="records"))
    return {"layer": layer_name, "columns": list(df.columns), "rows": records, "returned": len(records)}


def resolve_safe_project_file(rel_path: str) -> Path:
    """Safely resolves a relative project path and prevents directory traversal outside PROJECT_ROOT."""
    target = (PROJECT_ROOT / rel_path).resolve()
    root = PROJECT_ROOT.resolve()
    if root not in target.parents and target != root:
        raise PermissionError("Path escapes project root.")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"File not found: {rel_path}")
    return target


def bundle_shapefile_zip(shp_path: Path) -> bytes:
    """Bundles .shp + all matching sidecar files (.dbf, .shx, .prj, .cpg) into an in-memory ZIP."""
    buf = io.BytesIO()
    stem = shp_path.stem
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sidecar in shp_path.parent.glob(f"{stem}.*"):
            if sidecar.is_file():
                zf.write(sidecar, arcname=sidecar.name)
    return buf.getvalue()


def delete_asset_file(rel_path: str, area_id: Optional[str] = None) -> Dict[str, Any]:
    """Deletes a data asset file (and shapefile sidecars if .shp) strictly inside database/ or config/profiles/."""
    target = resolve_safe_project_file(rel_path)
    allowed_roots = [
        (PROJECT_ROOT / "database").resolve(),
        (PROJECT_ROOT / "config" / "profiles").resolve(),
    ]
    if not any(r in target.parents for r in allowed_roots):
        raise PermissionError("Deletion is restricted strictly to database/ assets and config/profiles/.")

    deleted = []
    if target.suffix.lower() == ".shp":
        for sidecar in target.parent.glob(f"{target.stem}.*"):
            if sidecar.is_file():
                sidecar.unlink()
                deleted.append(to_project_relative_posix(sidecar))
    else:
        target.unlink()
        deleted.append(to_project_relative_posix(target))

    studio_logger.warning(f"Deleted asset(s): {', '.join(deleted)}", section="DATA_MANAGER", area_id=area_id)
    return {"deleted": deleted}
