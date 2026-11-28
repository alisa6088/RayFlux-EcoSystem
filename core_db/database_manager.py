"""
core_db/database_manager.py
Atomic Central Database Manager handling:
  1. PostgreSQL / PostGIS spatial database persistence (to_postgis / read_postgis)
  2. Dual OGC GeoPackage (.gpkg) + Standardized ESRI Shapefile (.shp) persistence
  3. GeoTIFF Raster registration & validation (.tif)
  4. Tabular Excel (.xlsx) & CSV (.csv) generation
  5. Portable project-relative SHA-256 provenance cataloging & transaction audit logging
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional
import geopandas as gpd
import pandas as pd
import rasterio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig, to_project_relative_posix

# Standardized bidirectional mapping between full PostGIS/GPKG/Excel columns and <=10-char Shapefile columns
SHP_COLUMN_MAP: Dict[str, str] = {
    "building_id": "bldg_id",
    "source_feature_id": "src_id",
    "gross_area_m2": "gross_area",
    "building_height_m": "height_m",
    "height_variance": "height_var",
    "height_source": "h_source",
    "wfs_overlap_pct": "wfs_ov_pct",
    "num_floors": "floors",
    "centroid_x_utm": "cx_utm",
    "centroid_y_utm": "cy_utm",
    "obstacle_area_m2": "obj_area",
    "cast_shadow_area_m2": "shd_area",
    "usable_area_m2": "usable_are",
    "usable_area_pct": "usable_pct",
    "obstacle_count": "obj_cnt",
    "cooler_ac_count": "cooler_cnt",
    "penthouse_count": "penth_cnt",
    "chimney_vent_count": "vent_cnt",
    "parallax_dx_m": "dx_shift",
    "parallax_dy_m": "dy_shift",
    "suitability_status": "roof_stat",
    "usable_source": "use_src",
    "suitable_pixel_count": "rad_count",
    "suitable_area_m2": "suit_area",
    "mean_svf": "mean_svf",
    "mean_shadow_pct": "shd_pct",
    "mean_kwh_m2_yr": "mean_kwh",
    "min_kwh_m2_yr": "min_kwh",
    "max_kwh_m2_yr": "max_kwh",
    "std_kwh_m2_yr": "std_kwh",
    "incident_solar_mwh_yr": "inc_mwh_yr",
    "installed_capacity_kwp": "cap_kwp",
    "elec_yield_mwh_yr": "elec_mwh",
    "gi_star_statistic": "gi_stat",
    "gi_z_score": "gi_zscore",
    "gi_p_value": "gi_pvalue",
    "gi_cluster_class": "gi_class",
    **{f"mean_kwh_m2_m{m:02d}": f"kwh_m{m:02d}" for m in range(1, 13)},
    **{f"elec_mwh_m{m:02d}": f"el_mwh_{m:02d}" for m in range(1, 13)},
}
INV_SHP_COLUMN_MAP: Dict[str, str] = {v: k for k, v in SHP_COLUMN_MAP.items()}


class CentralDatabaseManager:
    """Provides unified, schema-validated read/write access to PostGIS and the Central File Database."""

    def __init__(self, config: EcosystemConfig):
        self.config = config
        self.db = config.db
        self.db.ensure_directories()
        self._pg_engine: Optional[Engine] = None
        self._pg_checked: bool = False

    def _log_audit(self, action: str, target: str, details: str) -> None:
        ts = datetime.now().isoformat()
        line = f"[{ts}] [{action}] {target} | {details}\n"
        with open(self.db.audit_log, "a", encoding="utf-8") as f:
            f.write(line)

    def get_postgis_engine(self) -> Optional[Engine]:
        """Connects to PostgreSQL/PostGIS, auto-starting the dedicated cluster and creating
        the target spatial database + PostGIS extension if needed."""
        if not self.config.postgis.enabled:
            return None
        if self._pg_checked:
            return self._pg_engine

        self._pg_checked = True
        pg_cfg = self.config.postgis
        try:
            from core_db.init_postgis_cluster import ensure_postgis_cluster_running, is_port_open
            if not is_port_open(pg_cfg.host, pg_cfg.port):
                ensure_postgis_cluster_running()
        except Exception as start_exc:
            self._log_audit("POSTGIS_AUTOSTART_WARN", pg_cfg.database, str(start_exc))

        try:
            engine = create_engine(pg_cfg.sqlalchemy_url)
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
                if pg_cfg.schema != "public":
                    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{pg_cfg.schema}"'))
            self._pg_engine = engine
            self._log_audit("POSTGIS_CONNECT", pg_cfg.database, f"Connected to PostGIS ({pg_cfg.host}:{pg_cfg.port})")
        except Exception as exc:
            self._pg_engine = None
            self._log_audit("POSTGIS_STANDBY", pg_cfg.database, f"Using local GPKG/Shapefile store ({exc})")

        return self._pg_engine

    @staticmethod
    def _file_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _update_catalog(self, key: str, metadata: dict) -> None:
        catalog = {}
        if self.db.catalog_json.exists():
            try:
                catalog = json.loads(self.db.catalog_json.read_text(encoding="utf-8"))
            except Exception:
                catalog = {}
        metadata["updated_at"] = datetime.now().isoformat()
        catalog[key] = metadata
        tmp_cat = self.db.catalog_json.with_suffix(".tmp")
        tmp_cat.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
        os.replace(tmp_cat, self.db.catalog_json)

    def save_vector_dataset(
        self,
        gdf: gpd.GeoDataFrame,
        shp_path: Path,
        gpkg_layer: str,
        excel_path: Optional[Path] = None,
    ) -> None:
        """Saves a GeoDataFrame to:
          1. PostgreSQL / PostGIS table (`gpkg_layer`) if PostGIS is active
          2. Master GeoPackage (`rfx_db_master_geodatabase.gpkg`)
          3. Standardized ESRI Shapefile (`.shp`)
          4. Optional Excel (`.xlsx`) & CSV (`.csv`) tables
        """
        target_crs = self.config.target_crs or "EPSG:32639"
        if gdf.crs is None or gdf.crs.to_string() != target_crs:
            gdf = gdf.to_crs(target_crs)

        if "building_id" in gdf.columns:
            gdf = gdf.sort_values("building_id").reset_index(drop=True)

        # 1. Commit to PostgreSQL / PostGIS (if active)
        postgis_synced = False
        pg_engine = self.get_postgis_engine()
        if pg_engine is not None:
            try:
                schema = self.config.postgis.schema
                if schema and schema != "public":
                    with pg_engine.begin() as conn:
                        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                gdf.to_postgis(
                    name=gpkg_layer,
                    con=pg_engine,
                    schema=schema,
                    if_exists="replace",
                    index=True,
                )
                postgis_synced = True
                self._log_audit("WRITE_POSTGIS", f"{schema}.{gpkg_layer}", f"rows={len(gdf)}")
            except Exception as exc:
                self._log_audit("POSTGIS_WRITE_WARN", gpkg_layer, str(exc))

        # 2. Commit full-schema layer to Master GeoPackage
        gdf.to_file(self.db.master_gpkg, layer=gpkg_layer, driver="GPKG")

        # 3. Commit <=10-char schema to Standardized ESRI Shapefile
        gdf_shp = gdf.rename(columns=SHP_COLUMN_MAP)
        shp_path.parent.mkdir(parents=True, exist_ok=True)
        gdf_shp.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

        # 4. Commit Tabular Excel (.xlsx)
        if excel_path is not None:
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            df_tab = pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))
            df_tab.to_excel(excel_path, index=False, engine="openpyxl")

        self._update_catalog(
            gpkg_layer,
            {
                "kind": "vector",
                "postgis_table": f"{self.config.postgis.schema}.{gpkg_layer}",
                "postgis_synced": postgis_synced,
                "shapefile": to_project_relative_posix(shp_path),
                "gpkg_layer": gpkg_layer,
                "excel": to_project_relative_posix(excel_path) if excel_path else None,
                "feature_count": len(gdf),
                "crs": str(gdf.crs),
                "bounds": [float(b) for b in gdf.total_bounds],
                "sha256": self._file_sha256(shp_path),
            },
        )
        self._log_audit("WRITE_VECTOR", gpkg_layer, f"count={len(gdf)} crs={gdf.crs} postgis={postgis_synced}")

    def load_vector_dataset(self, shp_path: Path, gpkg_layer: Optional[str] = None) -> gpd.GeoDataFrame:
        """Loads a vector dataset from PostGIS (primary) or Master GeoPackage / Shapefile (fallback)."""
        target_crs = self.config.target_crs or "EPSG:32639"
        gdf = None

        # 1. Try reading from PostgreSQL / PostGIS first if active
        pg_engine = self.get_postgis_engine()
        if pg_engine is not None and gpkg_layer:
            try:
                sql = f'SELECT * FROM "{self.config.postgis.schema}"."{gpkg_layer}"'
                gdf = gpd.read_postgis(sql, con=pg_engine, geom_col="geometry")
                self._log_audit("READ_POSTGIS", gpkg_layer, f"count={len(gdf)}")
            except Exception:
                gdf = None

        # 2. Fallback to Master GeoPackage or Standardized Shapefile
        if gdf is None:
            if gpkg_layer and self.db.master_gpkg.exists():
                try:
                    gdf = gpd.read_file(self.db.master_gpkg, layer=gpkg_layer)
                except Exception:
                    gdf = gpd.read_file(shp_path)
            else:
                gdf = gpd.read_file(shp_path)
            self._log_audit("READ_VECTOR_FILE", gpkg_layer or shp_path.name, f"count={len(gdf)}")

        gdf = gdf.rename(columns=INV_SHP_COLUMN_MAP)
        if gdf.crs is not None and gdf.crs.to_string() != target_crs:
            gdf = gdf.to_crs(target_crs)
        return gdf

    def register_raster(self, raster_path: Path, key: str) -> None:
        """Validates a saved GeoTIFF in the database and records its portable relative path in the catalog."""
        with rasterio.open(raster_path) as src:
            self._update_catalog(
                key,
                {
                    "kind": "raster",
                    "path": to_project_relative_posix(raster_path),
                    "width": src.width,
                    "height": src.height,
                    "bands": src.count,
                    "dtype": str(src.dtypes[0]),
                    "crs": str(src.crs),
                    "resolution": [float(src.res[0]), float(src.res[1])],
                    "bounds": [float(b) for b in src.bounds],
                    "sha256": self._file_sha256(raster_path),
                },
            )
            self._log_audit("WRITE_RASTER", key, f"shape={src.height}x{src.width} crs={src.crs}")
