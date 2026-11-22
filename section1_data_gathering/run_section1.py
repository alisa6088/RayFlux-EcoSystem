"""
section1_data_gathering/run_section1.py
Master runner for Section 1 (Data Gathering & Preprocessing Engine):
  1. Resolves the active Case Study AOI (from Shapefile, GeoJSON, or Bounding Box in config)
  2. Harvests 3D LoD1 Building Footprints & Heights from TUM WFS -> Saves to PostGIS + GPKG + .shp + .xlsx
  3. Builds the 0.50m Building-Only Synthetic DSM -> Saves to `rfx_s01_ras_synthetic_dsm.tif`
  4. Harvests Esri World Imagery PNG tiles -> Stitches & Warps to `rfx_s01_ras_ortho_rgb.tif`
  5. Renders QA/QC Overview Map (`rfx_s01_img_base_overview_map.png`)
"""
from pathlib import Path
import sys
import time
from typing import Optional, Tuple, Union
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig, to_project_relative_posix
from core_db.database_manager import CentralDatabaseManager
from section1_data_gathering.footprint_harvester import TUM3DFootprintHarvester
from section1_data_gathering.png_to_geotiff_harvester import harvest_esri_png_to_geotiff
from section1_data_gathering.synthetic_dsm_builder import build_synthetic_dsm_raster


def render_s01_overview_map(
    footprints_gdf: gpd.GeoDataFrame,
    dsm_path: Path,
    ortho_path: Path,
    out_png: Path,
) -> None:
    """Renders a 2-panel QA/QC overview map of the Esri Orthomosaic and Synthetic DSM."""
    fig, axes = plt.subplots(1, 2, figsize=(16, 7), dpi=180, facecolor="#141416")

    # Panel 1: Esri Orthomosaic + Footprints
    ax1 = axes[0]
    ax1.set_facecolor("#18181c")
    with rasterio.open(ortho_path) as src:
        scale = max(1, int(max(src.width, src.height) / 1200))
        out_h, out_w = src.height // scale, src.width // scale
        rgb = src.read(out_shape=(3, out_h, out_w))
        rgb = np.transpose(rgb, (1, 2, 0))
        extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
        ax1.imshow(rgb, extent=extent, origin="upper")

    footprints_gdf.boundary.plot(ax=ax1, color="#38BDF8", linewidth=0.6)
    ax1.set_title(
        f"1. High-Res Esri Orthomosaic + TUM 3D Footprints (N={len(footprints_gdf)})",
        color="#F4F4F5",
        fontsize=11,
        weight="bold",
    )
    ax1.tick_params(colors="#A1A1AA", labelsize=8)

    # Panel 2: Building-Only Synthetic DSM (0.5m)
    ax2 = axes[1]
    ax2.set_facecolor("#18181c")
    with rasterio.open(dsm_path) as src:
        scale = max(1, int(max(src.width, src.height) / 1200))
        dsm_preview = src.read(1, out_shape=(src.height // scale, src.width // scale))
        extent_dsm = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
        im = ax2.imshow(dsm_preview, extent=extent_dsm, cmap="magma", origin="upper")
        cbar = plt.colorbar(im, ax=ax2, fraction=0.046, pad=0.04)
        cbar.set_label("Building Height (m)", color="#F4F4F5", fontsize=9)
        cbar.ax.yaxis.set_tick_params(color="#A1A1AA", labelcolor="#A1A1AA")

    ax2.set_title(
        "2. Building-Only Synthetic DSM (0.50m Resolution)",
        color="#F4F4F5",
        fontsize=11,
        weight="bold",
    )
    ax2.tick_params(colors="#A1A1AA", labelsize=8)

    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=180, facecolor="#141416")
    plt.close(fig)


def run_section1(
    aoi_override: Optional[Union[EcosystemConfig, Path, str, Tuple[float, float, float, float]]] = None,
    config: Optional[EcosystemConfig] = None,
) -> None:
    t0 = time.time()
    if isinstance(aoi_override, EcosystemConfig):
        config = aoi_override
        aoi_override = None
    if config is None:
        config = EcosystemConfig()
    if aoi_override is not None:
        config.aoi_source = aoi_override

    config.db.ensure_directories()
    db_mgr = CentralDatabaseManager(config)
    aoi = config.resolve_aoi()

    print("=" * 78)
    print("RAYFLUX ECOSYSTEM — SECTION 1: DATA GATHERING & PREPROCESSING")
    print("=" * 78)
    print(f"  Case Study AOI Source : {aoi.source_description}")
    print(f"  Target Metric CRS     : {aoi.target_crs}")
    print(f"  Bounding Box (WGS84)  : {[round(x, 6) for x in aoi.bbox_wgs84]}")
    print(f"  Bounding Box (Metric) : {[round(x, 2) for x in aoi.bbox_utm]}")
    print("-" * 78)

    # 1. Harvest TUM 3D LoD1 Building Footprints & Heights
    harvester = TUM3DFootprintHarvester(config)
    footprints_gdf = harvester.harvest_aoi_footprints(aoi)
    db_mgr.save_vector_dataset(
        footprints_gdf,
        shp_path=config.db.s01_footprints_shp,
        gpkg_layer="s01_building_footprints",
        excel_path=config.db.s01_inventory_xlsx,
    )

    # 2. Build 0.50m Building-Only Synthetic DSM
    dsm_path = build_synthetic_dsm_raster(config, aoi, footprints_gdf)
    db_mgr.register_raster(dsm_path, "s01_synthetic_dsm")

    # 3. Harvest High-Resolution Esri World Imagery PNG Tiles -> Georeferenced GeoTIFF
    ortho_path = harvest_esri_png_to_geotiff(config, aoi)
    db_mgr.register_raster(ortho_path, "s01_ortho_rgb")

    # 4. Render QA/QC Overview Map
    render_s01_overview_map(
        footprints_gdf,
        dsm_path=dsm_path,
        ortho_path=ortho_path,
        out_png=config.db.s01_overview_map_png,
    )

    print("=" * 78)
    print(f"[Section 1] Completed successfully in {time.time() - t0:.2f}s!")
    print(f"  -> Footprints (.shp) : {to_project_relative_posix(config.db.s01_footprints_shp)}")
    print(f"  -> Inventory (.xlsx) : {to_project_relative_posix(config.db.s01_inventory_xlsx)}")
    print(f"  -> Synthetic DSM     : {to_project_relative_posix(config.db.s01_synthetic_dsm_tif)}")
    print(f"  -> High-Res Ortho    : {to_project_relative_posix(config.db.s01_ortho_tif)}")
    print(f"  -> Overview QA Map   : {to_project_relative_posix(config.db.s01_overview_map_png)}")
    print("=" * 78)


if __name__ == "__main__":
    run_section1()
