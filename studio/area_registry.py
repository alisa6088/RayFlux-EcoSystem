"""
studio/area_registry.py
Multi-Area Workspace Registry, Boundary Upload/Drawing Persistence, PostGIS Schema Management,
and Per-Area / Portfolio-Wide Building & Electricity Energy Statistics Engine.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Dict, List, Optional
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape
from sqlalchemy import text

from config.aoi_resolver import infer_utm_epsg_from_lonlat
from config.ecosystem_config import (
    DATA_INPUT_DIR,
    DB_ROOT,
    EcosystemConfig,
    PROJECT_ROOT,
    to_project_relative_posix,
)
from core_db.database_manager import CentralDatabaseManager
from studio.cv_profile_engine import (
    resolve_profile_path,
    save_profile,
    synthesize_cv_config,
)
from studio.smart_logger import studio_logger

REGISTRY_PATH = DB_ROOT / "core" / "rfx_areas_registry.json"
AREAS_DATA_DIR = PROJECT_ROOT / "data" / "areas"
AREAS_DB_DIR = DB_ROOT / "areas"

DEFAULT_AREA_ID = "area_default"


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug:
        slug = f"area_{int(datetime.now().timestamp())}"
    if slug[0].isdigit():
        slug = f"a_{slug}"
    return slug[:36]


class AreaRegistry:
    """Manages multiple study areas, their boundaries, PostGIS schemas, CV profiles, and energy KPIs."""

    def __init__(self, registry_path: Path = REGISTRY_PATH):
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        AREAS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        AREAS_DB_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_default_area()

    def _load_raw(self) -> Dict[str, Dict[str, Any]]:
        if not self.registry_path.exists():
            return {}
        try:
            return json.loads(self.registry_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_raw(self, data: Dict[str, Dict[str, Any]]) -> None:
        self.registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _extract_boundary_metadata(self, boundary_path: Path) -> Dict[str, Any]:
        """Reads a boundary file and computes WGS84 bounds, centroid, area_km2, and auto UTM EPSG."""
        gdf = gpd.read_file(boundary_path)
        if gdf.empty:
            raise ValueError("Boundary geometry file contains zero features.")
        if gdf.crs is None:
            gdf = gdf.set_crs("EPSG:4326")
        gdf_wgs = gdf.to_crs("EPSG:4326")
        minx, miny, maxx, maxy = [float(b) for b in gdf_wgs.total_bounds]
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0
        utm_crs = infer_utm_epsg_from_lonlat(cx, cy)
        gdf_utm = gdf_wgs.to_crs(utm_crs)
        area_km2 = float(gdf_utm.geometry.area.sum()) / 1e6
        return {
            "target_crs": utm_crs,
            "bounds_wgs84": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
            "center_latlon": [round(cy, 6), round(cx, 6)],
            "area_km2": round(area_km2, 3),
        }

    def _ensure_default_area(self) -> None:
        data = self._load_raw()
        if DEFAULT_AREA_ID in data:
            return
        default_shp = DATA_INPUT_DIR / "rfx_aoi_boundary.shp"
        meta = {
            "target_crs": "EPSG:32639",
            "bounds_wgs84": [50.259, 35.688, 50.336, 35.727],
            "center_latlon": [35.7075, 50.2981],
            "area_km2": 27.6,
        }
        if default_shp.exists():
            try:
                meta = self._extract_boundary_metadata(default_shp)
            except Exception:
                pass
        data[DEFAULT_AREA_ID] = {
            "area_id": DEFAULT_AREA_ID,
            "name": "Primary Industrial Park (Default)",
            "description": "Pre-processed 3,962-building industrial case study stored in public schema.",
            "area_types": ["industrial"],
            "traits": ["painted_metal_roofs", "corrugated_striping"],
            "aoi_path": to_project_relative_posix(default_shp),
            "db_root": "database",
            "postgis_schema": "public",
            "cv_profile": "default",
            "solar_config": "config/solar_parameters.yaml",
            "dsm_resolution_m": 0.50,
            "min_building_area_m2": 50.0,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            **meta,
        }
        self._save_raw(data)

    def list_areas(self) -> List[Dict[str, Any]]:
        data = self._load_raw()
        out = []
        for aid, item in data.items():
            enriched = dict(item)
            enriched["section_status"] = self._inspect_section_status(item)
            out.append(enriched)
        return out

    def get_area(self, area_id: str) -> Dict[str, Any]:
        data = self._load_raw()
        if area_id not in data:
            raise KeyError(f"Area '{area_id}' not found in registry.")
        item = dict(data[area_id])
        item["section_status"] = self._inspect_section_status(item)
        return item

    def build_ecosystem_config(self, area_id: str) -> EcosystemConfig:
        item = self.get_area(area_id)
        aoi_abs = PROJECT_ROOT / item["aoi_path"]
        db_root_abs = PROJECT_ROOT / item["db_root"]
        cv_yaml = resolve_profile_path(item.get("cv_profile"))
        solar_yaml = PROJECT_ROOT / item.get("solar_config", "config/solar_parameters.yaml")
        user_fp_rel = item.get("user_footprints_path")
        user_fp_abs = (PROJECT_ROOT / user_fp_rel) if user_fp_rel else None
        return EcosystemConfig.for_area(
            aoi_source=aoi_abs,
            db_root=db_root_abs,
            postgis_schema=item.get("postgis_schema", "public"),
            target_crs=item.get("target_crs"),
            cv_yaml=cv_yaml,
            solar_yaml=solar_yaml,
            dsm_resolution_m=float(item.get("dsm_resolution_m", 0.50)),
            min_building_area_m2=float(item.get("min_building_area_m2", 50.0)),
            footprint_mode=item.get("footprint_mode", "auto"),
            user_footprints_source=user_fp_abs,
        )

    def _inspect_section_status(self, item: Dict[str, Any]) -> Dict[str, Any]:
        db_root = PROJECT_ROOT / item["db_root"]
        cat_path = db_root / "core" / "rfx_db_asset_catalog.json"
        catalog = {}
        if cat_path.exists():
            try:
                catalog = json.loads(cat_path.read_text(encoding="utf-8"))
            except Exception:
                catalog = {}
        s1_done = "s01_building_footprints" in catalog and "s01_synthetic_dsm" in catalog
        s2_done = "s02_usable_rooftops" in catalog
        s3_done = "s03_solar_hotspots_final" in catalog
        return {
            "section1": s1_done,
            "section2": s2_done,
            "section3": s3_done,
            "buildings_count": int(catalog.get("s01_building_footprints", {}).get("feature_count", 0)),
            "obstacles_count": int(catalog.get("s02_physical_obstacles", {}).get("feature_count", 0)),
            "postgis_synced": bool(
                catalog.get("s03_solar_hotspots_final", catalog.get("s01_building_footprints", {})).get("postgis_synced", False)
            ),
        }

    def create_area_from_geojson(
        self,
        name: str,
        geojson_obj: Dict[str, Any],
        area_types: List[str],
        traits: Optional[List[str]] = None,
        description: str = "",
        cv_profile: Optional[str] = None,
        auto_generate_cv_yaml: bool = True,
        imagery_gsd_m: float = 0.45,
        dsm_resolution_m: float = 0.50,
        min_building_area_m2: float = 50.0,
        footprint_mode: str = "wfs_only",
    ) -> Dict[str, Any]:
        """Creates a new registered Area from a map-drawn GeoJSON Geometry/Feature/FeatureCollection."""
        data = self._load_raw()
        base_id = _slugify(name)
        area_id = base_id
        idx = 2
        while area_id in data:
            area_id = f"{base_id}_{idx}"
            idx += 1

        # Normalize GeoJSON to GeoDataFrame in EPSG:4326
        gtype = geojson_obj.get("type")
        if gtype == "FeatureCollection":
            geoms = [shape(f["geometry"]) for f in geojson_obj.get("features", []) if f.get("geometry")]
        elif gtype == "Feature":
            geoms = [shape(geojson_obj["geometry"])]
        else:
            geoms = [shape(geojson_obj)]

        if not geoms:
            raise ValueError("No valid polygon geometry provided.")

        gdf = gpd.GeoDataFrame({"area_id": [area_id] * len(geoms), "name": [name] * len(geoms)}, geometry=geoms, crs="EPSG:4326")

        area_dir = AREAS_DATA_DIR / area_id
        area_dir.mkdir(parents=True, exist_ok=True)
        geojson_path = area_dir / f"rfx_aoi_{area_id}.geojson"
        shp_path = area_dir / f"rfx_aoi_{area_id}.shp"

        eff_mode = (footprint_mode or "wfs_only").strip().lower()
        user_fp_path: Optional[Path] = None
        if eff_mode == "user_footprints":
            user_fp_path = area_dir / f"rfx_user_footprints_{area_id}.gpkg"
            gdf.to_file(user_fp_path, driver="GPKG")
            hull = gdf.geometry.unary_union.convex_hull
            env_gdf = gpd.GeoDataFrame({"area_id": [area_id], "name": [name]}, geometry=[hull], crs="EPSG:4326")
            env_gdf.to_file(geojson_path, driver="GeoJSON")
            env_gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")
        else:
            eff_mode = "wfs_only"
            gdf.to_file(geojson_path, driver="GeoJSON")
            gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

        return self._finalize_area_creation(
            area_id=area_id,
            name=name,
            description=description,
            boundary_path=shp_path,
            area_types=area_types,
            traits=traits or [],
            cv_profile=cv_profile,
            auto_generate_cv_yaml=auto_generate_cv_yaml,
            imagery_gsd_m=imagery_gsd_m,
            dsm_resolution_m=dsm_resolution_m,
            min_building_area_m2=min_building_area_m2,
            footprint_mode=eff_mode,
            user_footprints_path=user_fp_path,
        )

    def create_area_from_uploaded_files(
        self,
        name: str,
        uploaded_files: List[tuple],  # List of (filename, bytes)
        area_types: List[str],
        traits: Optional[List[str]] = None,
        description: str = "",
        cv_profile: Optional[str] = None,
        auto_generate_cv_yaml: bool = True,
        imagery_gsd_m: float = 0.45,
        dsm_resolution_m: float = 0.50,
        min_building_area_m2: float = 50.0,
        footprint_mode: str = "auto",
    ) -> Dict[str, Any]:
        """Creates a new registered Area from uploaded .geojson, .gpkg, .shp (+sidecars), or .zip shapefile bundle.
        When the uploaded file contains building footprints (`footprint_mode='user_footprints'` or
        `footprint_mode='auto'` with >1 polygon), preserves the user's exact building footprints in
        `rfx_user_footprints_<area_id>.gpkg` so Section 1 uses them directly and enriches heights from WFS overlap."""
        data = self._load_raw()
        base_id = _slugify(name)
        area_id = base_id
        idx = 2
        while area_id in data:
            area_id = f"{base_id}_{idx}"
            idx += 1

        requested_mode = (footprint_mode or "auto").strip().lower()
        user_fp_path: Optional[Path] = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for fname, raw_bytes in uploaded_files:
                safe_name = Path(fname).name
                dest = tmp / safe_name
                dest.write_bytes(raw_bytes)
                if dest.suffix.lower() == ".zip":
                    with zipfile.ZipFile(dest, "r") as zf:
                        zf.extractall(tmp)

            # Find primary vector file
            candidates = (
                list(tmp.rglob("*.shp"))
                + list(tmp.rglob("*.geojson"))
                + list(tmp.rglob("*.json"))
                + list(tmp.rglob("*.gpkg"))
            )
            if not candidates:
                raise ValueError("Uploaded archive/files did not contain a valid .shp, .geojson, or .gpkg file.")
            src_vec = candidates[0]
            gdf = gpd.read_file(src_vec)
            if gdf.empty:
                raise ValueError("Uploaded boundary/footprint file contains zero geometries.")
            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")

            # Keep only polygon features for building/AOI work
            gdf_poly = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
            gdf_poly = gdf_poly[gdf_poly.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
            if gdf_poly.empty:
                raise ValueError("Uploaded vector file contains no valid Polygon/MultiPolygon geometries.")

            is_user_footprints = (
                requested_mode == "user_footprints"
                or (requested_mode == "auto" and len(gdf_poly) > 1)
            )
            eff_mode = "user_footprints" if is_user_footprints else "wfs_only"

            area_dir = AREAS_DATA_DIR / area_id
            area_dir.mkdir(parents=True, exist_ok=True)
            shp_path = area_dir / f"rfx_aoi_{area_id}.shp"
            geojson_path = area_dir / f"rfx_aoi_{area_id}.geojson"

            gdf_wgs_full = gdf_poly.to_crs("EPSG:4326")
            if is_user_footprints:
                # Preserve the user's exact building footprints & attributes losslessly in GPKG
                user_fp_path = area_dir / f"rfx_user_footprints_{area_id}.gpkg"
                gdf_wgs_full.to_file(user_fp_path, driver="GPKG")

                # Build a clean outer boundary envelope for map display & AOI extent
                minx, miny, maxx, maxy = [float(b) for b in gdf_wgs_full.total_bounds]
                utm_crs = infer_utm_epsg_from_lonlat(0.5 * (minx + maxx), 0.5 * (miny + maxy))
                hull_utm = gdf_wgs_full.to_crs(utm_crs).geometry.unary_union.convex_hull.buffer(10.0)
                hull_wgs = gpd.GeoSeries([hull_utm], crs=utm_crs).to_crs("EPSG:4326").iloc[0]
                env_gdf = gpd.GeoDataFrame(
                    {"area_id": [area_id], "name": [name]},
                    geometry=[hull_wgs],
                    crs="EPSG:4326",
                )
                env_gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")
                env_gdf.to_file(geojson_path, driver="GeoJSON")
            else:
                gdf_wgs = gdf_wgs_full[["geometry"]].copy()
                gdf_wgs["area_id"] = area_id
                gdf_wgs["name"] = name
                gdf_wgs.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")
                gdf_wgs.to_file(geojson_path, driver="GeoJSON")

        return self._finalize_area_creation(
            area_id=area_id,
            name=name,
            description=description,
            boundary_path=shp_path,
            area_types=area_types,
            traits=traits or [],
            cv_profile=cv_profile,
            auto_generate_cv_yaml=auto_generate_cv_yaml,
            imagery_gsd_m=imagery_gsd_m,
            dsm_resolution_m=dsm_resolution_m,
            min_building_area_m2=min_building_area_m2,
            footprint_mode=eff_mode,
            user_footprints_path=user_fp_path,
        )

    def _finalize_area_creation(
        self,
        area_id: str,
        name: str,
        description: str,
        boundary_path: Path,
        area_types: List[str],
        traits: List[str],
        cv_profile: Optional[str],
        auto_generate_cv_yaml: bool,
        imagery_gsd_m: float,
        dsm_resolution_m: float,
        min_building_area_m2: float,
        footprint_mode: str = "auto",
        user_footprints_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        meta = self._extract_boundary_metadata(boundary_path)
        db_root = AREAS_DB_DIR / area_id
        db_root.mkdir(parents=True, exist_ok=True)

        chosen_profile = cv_profile or "default"
        if auto_generate_cv_yaml and area_types:
            synth = synthesize_cv_config(
                area_types=area_types,
                traits=traits,
                imagery_gsd_m=imagery_gsd_m,
                profile_name=f"area_{area_id}",
            )
            saved = save_profile(f"area_{area_id}", synth["yaml_text"], set_as_default=False)
            chosen_profile = saved["id"]

        record = {
            "area_id": area_id,
            "name": name.strip(),
            "description": description.strip(),
            "area_types": area_types or ["mixed_urban"],
            "traits": traits,
            "aoi_path": to_project_relative_posix(boundary_path),
            "footprint_mode": footprint_mode,
            "user_footprints_path": to_project_relative_posix(user_footprints_path) if user_footprints_path else None,
            "db_root": to_project_relative_posix(db_root),
            "postgis_schema": f"rfx_{area_id}",
            "cv_profile": chosen_profile,
            "solar_config": "config/solar_parameters.yaml",
            "dsm_resolution_m": float(dsm_resolution_m),
            "min_building_area_m2": float(min_building_area_m2),
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            **meta,
        }
        data = self._load_raw()
        data[area_id] = record
        self._save_raw(data)
        mode_note = "USER_FOOTPRINTS+WFS_HEIGHTS" if footprint_mode == "user_footprints" else "WFS_DIRECT"
        studio_logger.success(
            f"Registered new area '{name}' ({area_id}, {meta['area_km2']:.2f} km², mode={mode_note}, CRS={meta['target_crs']}, CV profile={chosen_profile})",
            section="AREA_MANAGER",
            area_id=area_id,
        )
        return self.get_area(area_id)

    def update_area(self, area_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        data = self._load_raw()
        if area_id not in data:
            raise KeyError(f"Area '{area_id}' not found.")
        allowed = {"name", "description", "area_types", "traits", "cv_profile", "dsm_resolution_m", "min_building_area_m2"}
        for k, v in updates.items():
            if k in allowed:
                data[area_id][k] = v
        self._save_raw(data)
        studio_logger.info(f"Updated settings for area '{area_id}'.", section="AREA_MANAGER", area_id=area_id)
        return self.get_area(area_id)

    def delete_area(self, area_id: str, drop_postgis: bool = True) -> Dict[str, Any]:
        if area_id == DEFAULT_AREA_ID:
            raise ValueError("Cannot delete the primary default area. Delete individual assets in Data Management instead.")
        data = self._load_raw()
        if area_id not in data:
            raise KeyError(f"Area '{area_id}' not found.")
        item = data.pop(area_id)
        self._save_raw(data)

        # Remove disk directories safely
        area_data_dir = AREAS_DATA_DIR / area_id
        area_db_dir = AREAS_DB_DIR / area_id
        if area_data_dir.exists():
            shutil.rmtree(area_data_dir, ignore_errors=True)
        if area_db_dir.exists():
            shutil.rmtree(area_db_dir, ignore_errors=True)

        # Drop isolated PostGIS schema
        schema = item.get("postgis_schema")
        pg_dropped = False
        if drop_postgis and schema and schema != "public":
            try:
                cfg = EcosystemConfig()
                eng = CentralDatabaseManager(cfg).get_postgis_engine()
                if eng is not None:
                    with eng.begin() as conn:
                        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                    pg_dropped = True
            except Exception as exc:
                studio_logger.warning(f"Could not drop PostGIS schema '{schema}': {exc}", section="AREA_MANAGER", area_id=area_id)

        studio_logger.warning(f"Deleted area '{area_id}' (PostGIS schema dropped={pg_dropped}).", section="AREA_MANAGER", area_id=area_id)
        return {"deleted": area_id, "postgis_schema_dropped": pg_dropped}

    def get_area_statistics(self, area_id: str, top_n: int = 50) -> Dict[str, Any]:
        """Computes exact building, rooftop, obstacle, PV capacity, monthly/annual electricity & Gi* stats."""
        item = self.get_area(area_id)
        db_root = PROJECT_ROOT / item["db_root"]
        gpkg = db_root / "core" / "rfx_db_master_geodatabase.gpkg"

        stats: Dict[str, Any] = {
            "area_id": area_id,
            "name": item["name"],
            "area_types": item.get("area_types", []),
            "area_km2": item.get("area_km2", 0.0),
            "target_crs": item.get("target_crs", "EPSG:32639"),
            "section_status": item["section_status"],
            "buildings_count": 0,
            "gross_area_m2": 0.0,
            "usable_area_m2": 0.0,
            "usable_pct": 0.0,
            "obstacle_area_m2": 0.0,
            "obstacle_count": 0,
            "shadow_area_m2": 0.0,
            "mean_irradiance_kwhm2": 0.0,
            "mean_svf": 0.0,
            "mean_shadow_pct": 0.0,
            "installed_capacity_mwp": 0.0,
            "annual_elec_gwh": 0.0,
            "annual_elec_mwh": 0.0,
            "mean_bldg_elec_mwh": 0.0,
            "median_bldg_elec_mwh": 0.0,
            "monthly_elec_gwh": [0.0] * 12,
            "gi_clusters": {},
            "suitability_counts": {},
            "top_buildings": [],
        }

        if not gpkg.exists():
            return stats

        # Prefer Section 3 final hotspots -> Section 2 usable rooftops -> Section 1 footprints
        gdf = None
        source_layer = None
        for lyr in ("s03_solar_hotspots_final", "s02_usable_rooftops", "s01_building_footprints"):
            try:
                gdf = gpd.read_file(gpkg, layer=lyr)
                source_layer = lyr
                break
            except Exception:
                continue

        if gdf is None or gdf.empty:
            return stats

        stats["buildings_count"] = int(len(gdf))
        if "gross_area_m2" in gdf.columns:
            stats["gross_area_m2"] = round(float(gdf["gross_area_m2"].sum()), 1)
        if "usable_area_m2" in gdf.columns:
            stats["usable_area_m2"] = round(float(gdf["usable_area_m2"].sum()), 1)
        if stats["gross_area_m2"] > 0 and stats["usable_area_m2"] > 0:
            stats["usable_pct"] = round(stats["usable_area_m2"] / stats["gross_area_m2"] * 100.0, 1)
        if "obstacle_area_m2" in gdf.columns:
            stats["obstacle_area_m2"] = round(float(gdf["obstacle_area_m2"].sum()), 1)
        if "obstacle_count" in gdf.columns:
            stats["obstacle_count"] = int(gdf["obstacle_count"].sum())
        if "cast_shadow_area_m2" in gdf.columns:
            stats["shadow_area_m2"] = round(float(gdf["cast_shadow_area_m2"].sum()), 1)
        if "suitability_status" in gdf.columns:
            stats["suitability_counts"] = {str(k): int(v) for k, v in gdf["suitability_status"].value_counts().items()}

        if source_layer == "s03_solar_hotspots_final":
            stats["mean_irradiance_kwhm2"] = round(float(gdf["mean_kwh_m2_yr"].mean()), 1)
            stats["mean_svf"] = round(float(gdf["mean_svf"].mean()), 3) if "mean_svf" in gdf.columns else 0.0
            stats["mean_shadow_pct"] = round(float(gdf["mean_shadow_pct"].mean()), 2) if "mean_shadow_pct" in gdf.columns else 0.0
            stats["installed_capacity_mwp"] = round(float(gdf["installed_capacity_kwp"].sum()) / 1000.0, 2)
            total_mwh = float(gdf["elec_yield_mwh_yr"].sum())
            stats["annual_elec_mwh"] = round(total_mwh, 1)
            stats["annual_elec_gwh"] = round(total_mwh / 1000.0, 2)
            stats["mean_bldg_elec_mwh"] = round(float(gdf["elec_yield_mwh_yr"].mean()), 1)
            stats["median_bldg_elec_mwh"] = round(float(gdf["elec_yield_mwh_yr"].median()), 1)
            stats["monthly_elec_gwh"] = [
                round(float(gdf[f"elec_mwh_m{m:02d}"].sum()) / 1000.0, 2)
                if f"elec_mwh_m{m:02d}" in gdf.columns
                else 0.0
                for m in range(1, 13)
            ]
            if "gi_cluster_class" in gdf.columns:
                stats["gi_clusters"] = {str(k): int(v) for k, v in gdf["gi_cluster_class"].value_counts().items()}

        # Top-N buildings with WGS84 centroid coordinates for map click-to-zoom
        sort_col = (
            "elec_yield_mwh_yr"
            if "elec_yield_mwh_yr" in gdf.columns
            else ("usable_area_m2" if "usable_area_m2" in gdf.columns else "gross_area_m2")
        )
        top_df = gdf.nlargest(min(top_n, len(gdf)), sort_col).copy()
        centroids_wgs = top_df.geometry.centroid.to_crs("EPSG:4326")
        top_rows = []
        for idx, row in enumerate(top_df.itertuples(index=False)):
            pt = centroids_wgs.iloc[idx]
            top_rows.append({
                "building_id": int(getattr(row, "building_id", idx + 1)),
                "gross_area_m2": round(float(getattr(row, "gross_area_m2", 0.0)), 1),
                "usable_area_m2": round(float(getattr(row, "usable_area_m2", 0.0)), 1),
                "usable_area_pct": round(float(getattr(row, "usable_area_pct", 0.0)), 1),
                "obstacle_count": int(getattr(row, "obstacle_count", 0)),
                "mean_kwh_m2_yr": round(float(getattr(row, "mean_kwh_m2_yr", 0.0)), 1),
                "installed_capacity_kwp": round(float(getattr(row, "installed_capacity_kwp", 0.0)), 1),
                "elec_yield_mwh_yr": round(float(getattr(row, "elec_yield_mwh_yr", 0.0)), 1),
                "gi_cluster_class": str(getattr(row, "gi_cluster_class", "N/A")),
                "lat": round(float(pt.y), 6),
                "lon": round(float(pt.x), 6),
            })
        stats["top_buildings"] = top_rows
        return stats

    def get_portfolio_statistics(self) -> Dict[str, Any]:
        """Aggregates KPIs and monthly electricity profiles across ALL registered active areas."""
        areas = self.list_areas()
        per_area = [self.get_area_statistics(a["area_id"], top_n=15) for a in areas]
        monthly_total = [round(sum(a["monthly_elec_gwh"][m] for a in per_area), 2) for m in range(12)]
        gi_agg: Dict[str, int] = {}
        for a in per_area:
            for k, v in a["gi_clusters"].items():
                gi_agg[k] = gi_agg.get(k, 0) + v

        return {
            "total_areas": len(per_area),
            "total_buildings": sum(a["buildings_count"] for a in per_area),
            "total_gross_ha": round(sum(a["gross_area_m2"] for a in per_area) / 1e4, 2),
            "total_usable_ha": round(sum(a["usable_area_m2"] for a in per_area) / 1e4, 2),
            "total_obstacles": sum(a["obstacle_count"] for a in per_area),
            "total_capacity_mwp": round(sum(a["installed_capacity_mwp"] for a in per_area), 2),
            "total_annual_gwh": round(sum(a["annual_elec_gwh"] for a in per_area), 2),
            "monthly_elec_gwh": monthly_total,
            "gi_clusters": gi_agg,
            "areas": per_area,
        }


area_registry = AreaRegistry()
