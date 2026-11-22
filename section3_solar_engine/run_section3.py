"""
section3_solar_engine/run_section3.py
Master standalone orchestrator for Section 3: Main Solar Physics, 32-Direction Horizon Shading,
Monthly & Annual PV Electricity Yield, and Getis-Ord Gi* Spatial Hotspot Engine.

Pipeline:
  1. Loads Section 1 Synthetic DSM (`rfx_s01_ras_synthetic_dsm.tif`), Section 1 3D Building Footprints
     (`public.s01_building_footprints`), and Section 2 Obstacle-Free Usable Rooftops
     (`public.s02_usable_rooftops`) from the Central Geospatial Database (PostGIS primary).
  2. Step 3.1: Generates UTC solar position & pvlib Haurwitz clear-sky irradiance grid.
  3. Steps 3.2–3.4: Streams 512x512 tiles through Numba-compiled 32-dir bilinear horizon ray-marching,
     hemispherical SVF, 12 monthly + annual irradiance rasters, daytime shadow %, and suitability mask.
  4. Steps 3.5–3.6: Computes vectorized zonal statistics over obstacle-free usable roof polygons,
     calculates installed PV capacity (MWp) and monthly/annual yield (MWh/yr), and executes
     Getis-Ord Gi* hotspot clustering (KNN=5, 999 Monte Carlo permutations).
  5. Commits all vector layers to PostGIS + Master GeoPackage + `.shp` + single Excel `.xlsx` workbook,
     registers all GeoTIFF rasters in the SHA-256 asset catalog, and renders 3 executive visual maps.
"""
from pathlib import Path
import sys
import time
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig, to_project_relative_posix
from core_db.database_manager import CentralDatabaseManager
from section3_solar_engine.horizon_radiation_engine import run_horizon_and_radiation
from section3_solar_engine.solar_config import SolarParameters
from section3_solar_engine.solar_geometry import generate_solar_geometry
from section3_solar_engine.visualizer import (
    render_energy_distribution,
    render_hotspots_cluster_map,
    render_irradiance_heatmap,
)
from section3_solar_engine.zonal_energy_hotspots import compute_zonal_energy_and_hotspots


def run_section3(config: EcosystemConfig = None, reuse_existing_rasters: bool = False) -> Dict[str, Any]:
    t0 = time.time()
    cfg = config or EcosystemConfig()
    cfg.db.ensure_directories()
    db_mgr = CentralDatabaseManager(cfg)
    params = SolarParameters.load_yaml(cfg.solar_params_yaml)

    print("=" * 76)
    print("  RAYFLUX ECOSYSTEM — SECTION 3: SOLAR PHYSICS, PV YIELD & HOTSPOTS ENGINE")
    print("=" * 76)
    print(f"[S3] Parameters loaded from: {to_project_relative_posix(cfg.solar_params_yaml)}")

    if not cfg.db.s01_synthetic_dsm_tif.exists():
        raise FileNotFoundError(
            f"Missing Section 1 Synthetic DSM: {to_project_relative_posix(cfg.db.s01_synthetic_dsm_tif)}"
        )

    # 1. Load vector layers from PostGIS (or GPKG/SHP fallback)
    print("[S3] Loading Section 1 footprints (public.s01_building_footprints)...")
    footprints_gdf = db_mgr.load_vector_dataset(cfg.db.s01_footprints_shp, gpkg_layer="s01_building_footprints")
    print(f"     -> Loaded {len(footprints_gdf):,} 3D building footprints (CRS={footprints_gdf.crs}).")

    usable_gdf = None
    used_section2 = False
    if params.pv_system.use_section2_usable_polygons:
        try:
            usable_gdf = db_mgr.load_vector_dataset(cfg.db.s02_usable_rooftops_shp, gpkg_layer="s02_usable_rooftops")
            if usable_gdf is not None and not usable_gdf.empty:
                used_section2 = True
                print(
                    f"[S3] Loaded Section 2 obstacle-free usable rooftops (public.s02_usable_rooftops): "
                    f"{len(usable_gdf):,} polygons (replaces legacy 70% assumption)."
                )
        except Exception as exc:
            print(f"[S3] Note: Section 2 usable rooftops unavailable ({exc}); falling back to {params.pv_system.fallback_usable_ratio*100:.0f}% flat-roof ratio.")

    # 2. Step 3.1 — Solar Geometry & Clear-Sky Irradiance Grid
    print("[S3] Step 3.1: Generating UTC solar geometry & pvlib Haurwitz clear-sky grid...")
    sun_df, geom_meta = generate_solar_geometry(
        dsm_path=cfg.db.s01_synthetic_dsm_tif,
        out_csv_path=cfg.db.s03_solar_geom_csv,
        params=params,
    )
    print(
        f"     -> Center=({geom_meta['center_lat']}, {geom_meta['center_lon']}), "
        f"Alt={geom_meta['altitude_m']} m | {geom_meta['sample_days']} days ({geom_meta['daytime_timesteps']} daytime steps) | "
        f"Theoretical Unshaded GHI={geom_meta['unshaded_annual_ghi_kwhm2']:.1f} kWh/m²/yr"
    )

    # 3. Steps 3.2–3.4 — Numba 32-Dir Bilinear Horizon, SVF, Monthly & Annual Irradiance, Suitability
    rasters_exist = (
        cfg.db.s03_annual_rad_tif.exists()
        and cfg.db.s03_svf_tif.exists()
        and cfg.db.s03_shadow_frac_tif.exists()
        and cfg.db.s03_suitability_tif.exists()
        and all(cfg.db.monthly_rad_tif(m).exists() for m in range(1, 13))
    )
    if reuse_existing_rasters and rasters_exist:
        print("[S3] Steps 3.2–3.4: Reusing verified Section 3 horizon & irradiance GeoTIFF rasters from database.")
        rad_meta = {"reused_existing_rasters": True}
    else:
        print("[S3] Steps 3.2–3.4: Running 32-direction horizon shading & monthly/annual irradiance integration...")
        rad_meta = run_horizon_and_radiation(
            dsm_path=cfg.db.s01_synthetic_dsm_tif,
            footprints_gdf=footprints_gdf,
            sun_df=sun_df,
            db=cfg.db,
            params=params,
        )
        print("[S3] Registering Section 3 GeoTIFF rasters in Central Asset Catalog...")
        db_mgr.register_raster(cfg.db.s03_horizon_tif, "s03_horizon_angles_32dir")
        db_mgr.register_raster(cfg.db.s03_svf_tif, "s03_sky_view_factor")
        db_mgr.register_raster(cfg.db.s03_annual_rad_tif, "s03_irradiance_annual")
        db_mgr.register_raster(cfg.db.s03_shadow_frac_tif, "s03_shadow_fraction_annual")
        db_mgr.register_raster(cfg.db.s03_suitability_tif, "s03_suitability_mask")

    # 4. Steps 3.5–3.6 — Obstacle-Free Zonal Stats, PV Energy Yield & Getis-Ord Gi* Hotspots
    print("[S3] Steps 3.5–3.6: Computing zonal stats, PV capacity/yield & Getis-Ord Gi* hotspots...")
    zonal_gdf, hotspots_gdf, energy_meta = compute_zonal_energy_and_hotspots(
        footprints_gdf=footprints_gdf,
        usable_gdf=usable_gdf,
        db=cfg.db,
        params=params,
        used_section2=used_section2,
    )

    # 5. Commit Section 3 Vector & Single Excel (.xlsx) Outputs to PostGIS + GPKG + Shapefile
    print("[S3] Committing public.s03_solar_zonal_stats to PostGIS, GPKG & Shapefile...")
    db_mgr.save_vector_dataset(
        gdf=zonal_gdf,
        shp_path=cfg.db.s03_zonal_stats_shp,
        gpkg_layer="s03_solar_zonal_stats",
        excel_path=None,
    )

    print("[S3] Committing public.s03_solar_hotspots_final to PostGIS, GPKG, Shapefile & Excel (.xlsx)...")
    db_mgr.save_vector_dataset(
        gdf=hotspots_gdf,
        shp_path=cfg.db.s03_hotspots_final_shp,
        gpkg_layer="s03_solar_hotspots_final",
        excel_path=cfg.db.s03_solar_final_xlsx,
    )

    # 6. Render 3 Executive Cartographic & Analytical Visuals
    print("[S3] Rendering executive maps and PV energy dashboard...")
    ortho_opt = cfg.db.s01_ortho_tif if cfg.db.s01_ortho_tif.exists() else None
    render_irradiance_heatmap(
        annual_rad_tif=cfg.db.s03_annual_rad_tif,
        ortho_tif=ortho_opt,
        hotspots_gdf=hotspots_gdf,
        out_png=cfg.db.s03_rad_heatmap_png,
    )
    render_hotspots_cluster_map(
        hotspots_gdf=hotspots_gdf,
        ortho_tif=ortho_opt,
        out_png=cfg.db.s03_hotspots_map_png,
    )
    render_energy_distribution(
        hotspots_gdf=hotspots_gdf,
        out_png=cfg.db.s03_energy_dist_png,
    )

    # 7. Automated QA Self-Audit
    nan_count = int(
        hotspots_gdf[["mean_kwh_m2_yr", "installed_capacity_kwp", "elec_yield_mwh_yr", "gi_z_score"]]
        .isna()
        .sum()
        .sum()
    )
    elapsed = time.time() - t0

    print("=" * 76)
    print(f"  SECTION 3 COMPLETE in {elapsed:.1f}s")
    print(f"  Usable Roof Source     : {energy_meta['usable_source']}")
    print(f"  Buildings Analyzed     : {energy_meta['buildings_analyzed']:,}")
    print(f"  Net Usable Roof Area   : {energy_meta['total_usable_area_m2']:,.1f} m² ({energy_meta['total_usable_area_m2']/1e4:.2f} ha)")
    print(f"  Mean Annual Irradiance : {energy_meta['mean_annual_rad_kwhm2']:,.1f} kWh/m²/yr (Unshaded Ref: {geom_meta['unshaded_annual_ghi_kwhm2']:,.1f})")
    print(f"  Installed PV Capacity  : {energy_meta['total_capacity_mwp']:,.2f} MWp")
    print(f"  Annual PV Generation   : {energy_meta['total_elec_gwh_yr']:,.2f} GWh/year")
    print(f"  Gi* Clusters           : {energy_meta['cluster_counts']}")
    print(f"  QA Self-Audit          : NaNs={nan_count} | Monthly-vs-Annual Drift={energy_meta['monthly_vs_annual_diff_pct']:.4f}%")
    print(f"  Final Excel Report     : {to_project_relative_posix(cfg.db.s03_solar_final_xlsx)}")
    print(f"  Irradiance Heatmap     : {to_project_relative_posix(cfg.db.s03_rad_heatmap_png)}")
    print(f"  Hotspot Cluster Map    : {to_project_relative_posix(cfg.db.s03_hotspots_map_png)}")
    print(f"  PV Energy Dashboard    : {to_project_relative_posix(cfg.db.s03_energy_dist_png)}")
    print("=" * 76)

    return {
        "solar_geometry": geom_meta,
        "radiation": rad_meta,
        "energy_hotspots": energy_meta,
        "qa_nans": nan_count,
        "elapsed_sec": round(elapsed, 2),
    }


if __name__ == "__main__":
    reuse = "--reuse-rasters" in sys.argv
    run_section3(reuse_existing_rasters=reuse)
