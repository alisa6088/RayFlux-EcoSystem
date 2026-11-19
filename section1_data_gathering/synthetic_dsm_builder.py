"""
section1_data_gathering/synthetic_dsm_builder.py
Generates the high-precision 0.50m Building-Only Synthetic Digital Surface Model
(`rfx_s01_ras_synthetic_dsm.tif`) by burning the 3D TUM building heights onto a
metric elevation grid with ground level set to 0.0m.
"""
import math
from pathlib import Path
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.aoi_resolver import ResolvedAOI
from config.ecosystem_config import EcosystemConfig


def build_synthetic_dsm_raster(
    config: EcosystemConfig,
    aoi: ResolvedAOI,
    footprints_gdf: gpd.GeoDataFrame,
) -> Path:
    """Rasterizes `building_height_m` onto a 0.50m metric grid over the AOI extent."""
    xmin, ymin, xmax, ymax = aoi.bbox_utm
    res = config.dsm_resolution_m

    width = int(math.ceil((xmax - xmin) / res))
    height_dim = int(math.ceil((ymax - ymin) / res))
    transform = from_origin(xmin, ymax, res, res)

    print(
        f"[Section 1 | Synthetic DSM] Rasterizing {len(footprints_gdf)} 3D buildings "
        f"onto {width}x{height_dim} grid (res={res}m)..."
    )

    if len(footprints_gdf) > 0:
        shapes = (
            (geom, float(h))
            for geom, h in zip(footprints_gdf.geometry, footprints_gdf["building_height_m"])
        )
        dsm_array = rasterize(
            shapes=shapes,
            out_shape=(height_dim, width),
            transform=transform,
            fill=0.0,
            dtype="float32",
        )
    else:
        dsm_array = np.zeros((height_dim, width), dtype="float32")

    out_path = config.db.s01_synthetic_dsm_tif
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=height_dim,
        width=width,
        count=1,
        dtype="float32",
        crs=aoi.target_crs,
        transform=transform,
        compress="lzw",
        predictor=2,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        nodata=-9999.0,
    ) as dst:
        dst.write(dsm_array, 1)

    print(f"[Section 1 | Synthetic DSM] Saved to: {out_path}")
    return out_path
