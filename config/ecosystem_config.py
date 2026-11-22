"""
config/ecosystem_config.py
Master global configuration, PostGIS connection settings, universal Case Study AOI resolver,
and standardized rfx_* file path registry for the RayFlux Ecosystem.
All paths are resolved dynamically relative to PROJECT_ROOT for 100% cross-machine portability.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Optional, Tuple, Union

from config.aoi_resolver import ResolvedAOI, resolve_case_study_aoi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_INPUT_DIR = PROJECT_ROOT / "data" / "case_study_aoi"
DB_ROOT = PROJECT_ROOT / "database"
LOGS_DIR = PROJECT_ROOT / "logs"


def to_project_relative_posix(path: Union[Path, str]) -> str:
    """Converts a path into a portable POSIX path relative to PROJECT_ROOT."""
    p = Path(path).resolve()
    try:
        return p.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


@dataclass
class PostGISConfig:
    """PostgreSQL / PostGIS spatial database configuration for vector shapefile layers."""

    enabled: bool = True
    host: str = os.getenv("RFX_PG_HOST", "127.0.0.1")
    port: int = int(os.getenv("RFX_PG_PORT", "5433"))
    database: str = os.getenv("RFX_PG_DATABASE", "rayflux_spatial_db")
    schema: str = os.getenv("RFX_PG_SCHEMA", "public")
    user: str = os.getenv("RFX_PG_USER", "rayflux_admin")
    password: str = os.getenv("RFX_PG_PASSWORD", "RayFlux_2026_Pass")

    @property
    def sqlalchemy_url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    @property
    def admin_url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/postgres"


@dataclass
class DatabasePaths:
    """Standardized rfx_<sec>_<kind>_<descriptor>.<ext> database file addresses."""

    # Core Database Infrastructure (database/core/)
    master_gpkg: Path = DB_ROOT / "core" / "rfx_db_master_geodatabase.gpkg"
    catalog_json: Path = DB_ROOT / "core" / "rfx_db_asset_catalog.json"
    audit_log: Path = DB_ROOT / "core" / "rfx_db_transaction_audit.log"

    # Section 1: Data Gathering & Preprocessing Store (s01_base)
    tile_cache_dir: Path = DB_ROOT / "cache" / "s01_tiles"
    s01_ortho_tif: Path = DB_ROOT / "rasters" / "s01_base" / "rfx_s01_ras_ortho_rgb.tif"
    s01_synthetic_dsm_tif: Path = DB_ROOT / "rasters" / "s01_base" / "rfx_s01_ras_synthetic_dsm.tif"
    s01_footprints_shp: Path = DB_ROOT / "shapefiles" / "s01_base" / "rfx_s01_vec_building_footprints.shp"
    s01_inventory_xlsx: Path = DB_ROOT / "tables" / "s01_base" / "rfx_s01_tbl_building_inventory.xlsx"
    s01_overview_map_png: Path = DB_ROOT / "maps" / "s01_base" / "rfx_s01_img_base_overview_map.png"

    # Section 2: Rooftop Object Detection Store (s02_vision)
    s02_usable_rooftops_shp: Path = DB_ROOT / "shapefiles" / "s02_vision" / "rfx_s02_vec_usable_rooftops.shp"
    s02_obstacles_shp: Path = DB_ROOT / "shapefiles" / "s02_vision" / "rfx_s02_vec_physical_obstacles.shp"
    s02_shadows_shp: Path = DB_ROOT / "shapefiles" / "s02_vision" / "rfx_s02_vec_cast_shadows.shp"
    s02_usable_report_xlsx: Path = DB_ROOT / "tables" / "s02_vision" / "rfx_s02_tbl_usable_area_report.xlsx"
    s02_scene_map_png: Path = DB_ROOT / "maps" / "s02_vision" / "rfx_s02_img_scene_detection_map.png"
    s02_cards_dir: Path = DB_ROOT / "maps" / "s02_vision" / "cards"

    # Section 3: Main Solar & Energy Store (s03_solar)
    s03_solar_geom_csv: Path = DB_ROOT / "tables" / "s03_solar" / "rfx_s03_tbl_solar_geometry.csv"
    s03_horizon_tif: Path = DB_ROOT / "rasters" / "s03_solar" / "rfx_s03_ras_horizon_angles_32dir.tif"
    s03_svf_tif: Path = DB_ROOT / "rasters" / "s03_solar" / "rfx_s03_ras_sky_view_factor.tif"
    s03_annual_rad_tif: Path = DB_ROOT / "rasters" / "s03_solar" / "rfx_s03_ras_irradiance_annual.tif"
    s03_shadow_frac_tif: Path = DB_ROOT / "rasters" / "s03_solar" / "rfx_s03_ras_shadow_fraction_annual.tif"
    s03_suitability_tif: Path = DB_ROOT / "rasters" / "s03_solar" / "rfx_s03_ras_suitability_mask.tif"
    s03_monthly_rad_dir: Path = DB_ROOT / "rasters" / "s03_solar" / "monthly"
    s03_zonal_stats_shp: Path = DB_ROOT / "shapefiles" / "s03_solar" / "rfx_s03_vec_solar_zonal_stats.shp"
    s03_hotspots_final_shp: Path = DB_ROOT / "shapefiles" / "s03_solar" / "rfx_s03_vec_solar_hotspots_final.shp"
    s03_solar_final_xlsx: Path = DB_ROOT / "tables" / "s03_solar" / "rfx_s03_tbl_solar_potential_final.xlsx"
    s03_rad_heatmap_png: Path = DB_ROOT / "maps" / "s03_solar" / "rfx_s03_img_irradiance_heatmap.png"
    s03_hotspots_map_png: Path = DB_ROOT / "maps" / "s03_solar" / "rfx_s03_img_hotspots_cluster_map.png"
    s03_energy_dist_png: Path = DB_ROOT / "maps" / "s03_solar" / "rfx_s03_img_energy_distribution.png"

    def monthly_rad_tif(self, month_idx: int) -> Path:
        """Returns standardized path for monthly irradiance raster (m01..m12)."""
        return self.s03_monthly_rad_dir / f"rfx_s03_ras_irradiance_m{month_idx:02d}.tif"

    def roof_diag_card_png(self, building_id: int) -> Path:
        """Returns standardized path for per-building diagnostic card PNG."""
        return self.s02_cards_dir / f"rfx_s02_img_roof_diag_bldg_{building_id:04d}.png"

    def ensure_directories(self) -> None:
        """Creates all required input data, database, and log directories on disk."""
        DATA_INPUT_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        for val in self.__dict__.values():
            if isinstance(val, Path):
                target_dir = val if val.suffix == "" else val.parent
                target_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class EcosystemConfig:
    """Global Master Configuration governing the active Case Study AOI, PostGIS, and all 3 Sections.

    `aoi_source` can be set to:
      - A Shapefile path (.shp) inside `data/case_study_aoi/`
      - A GeoJSON (.geojson) or GeoPackage (.gpkg) path
      - Or a 4-tuple Bounding Box (west, south, east, north) in EPSG:4326
    """

    # Universal Case Study AOI Input (Shapefile, GeoJSON, or Bounding Box tuple)
    aoi_source: Union[Path, str, Tuple[float, float, float, float]] = field(
        default_factory=lambda: Path(os.getenv("RFX_AOI_SOURCE", str(DATA_INPUT_DIR / "rfx_aoi_boundary.shp")))
    )
    aoi_buffer_m: float = 15.0
    target_crs: Optional[str] = "EPSG:32639"
    min_building_area_m2: float = 50.0
    default_building_height_m: float = 9.6

    # Section 1 Parameters (3D LoD1 WFS + High-Res Satellite Imagery + Synthetic DSM)
    tum_wfs_base_url: str = "https://tubvsig-so2sat-vm1.srv.mwn.de"
    tum_grid_step_deg: float = 0.04
    imagery_provider: str = "esri"
    imagery_zoom: int = 19
    imagery_download_workers: int = 12
    dsm_resolution_m: float = 0.50

    # Section 2 Parameters (Rooftop Object Detection)
    min_obstacle_area_m2: float = 0.20
    min_usable_patch_m2: float = 2.00
    cv_hyperparams_yaml: Path = PROJECT_ROOT / "config" / "cv_hyperparameters.yaml"

    # Section 3 Parameters (Solar Physics & Spatial Hotspots)
    solar_params_yaml: Path = PROJECT_ROOT / "config" / "solar_parameters.yaml"
    timezone: str = "UTC"
    year: int = 2024
    altitude_m: float = 1200.0
    day_interval: int = 14
    hour_interval: float = 0.5
    n_directions: int = 32
    max_shadow_distance_m: float = 500.0
    ray_step_size_m: float = 1.0
    diffuse_fraction: float = 0.20
    min_suitable_rad_kwhm2: float = 400.0
    pv_efficiency: float = 0.20
    performance_ratio: float = 0.86
    knn_neighbors: int = 5
    mc_permutations: int = 999

    postgis: PostGISConfig = field(default_factory=PostGISConfig)
    db: DatabasePaths = field(default_factory=DatabasePaths)

    def resolve_aoi(self) -> ResolvedAOI:
        """Resolves `self.aoi_source` into a standardized ResolvedAOI extent and boundary."""
        resolved = resolve_case_study_aoi(
            self.aoi_source,
            target_crs=self.target_crs,
            buffer_m=self.aoi_buffer_m,
        )
        if self.target_crs is None:
            self.target_crs = resolved.target_crs
        return resolved
