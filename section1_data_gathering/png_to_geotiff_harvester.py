"""
section1_data_gathering/png_to_geotiff_harvester.py
Harvests high-resolution satellite PNG slippy-map tiles from Esri World Imagery,
automatically verifies the highest native non-placeholder zoom level, caches PNG tiles,
stitches them into a continuous canvas, injects spatial bounds, and warps to the
unified metric target CRS (`rfx_s01_ras_ortho_rgb.tif`).
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Tuple
import mercantile
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, calculate_default_transform, reproject
import requests

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.aoi_resolver import ResolvedAOI
from config.ecosystem_config import EcosystemConfig

Image.MAX_IMAGE_PIXELS = None

ESRI_WORLD_IMAGERY_TPL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
ESRI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.arcgis.com/",
}


def detect_best_esri_zoom(
    bbox_wgs84: Tuple[float, float, float, float],
    preferred_zoom: int = 19,
    min_zoom: int = 16,
) -> int:
    """Probes the center tile of the AOI to find the highest zoom level where Esri World Imagery
    serves real high-resolution imagery rather than a flat gray 'Map data not yet available' tile."""
    west, south, east, north = bbox_wgs84
    for z in range(preferred_zoom, min_zoom - 1, -1):
        tiles = list(mercantile.tiles(west, south, east, north, z))
        if not tiles:
            continue
        mid_tile = tiles[len(tiles) // 2]
        url = ESRI_WORLD_IMAGERY_TPL.format(z=mid_tile.z, y=mid_tile.y, x=mid_tile.x)
        try:
            resp = requests.get(url, headers=ESRI_HEADERS, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 3500:
                arr = np.array(Image.open(BytesIO(resp.content)).convert("RGB"))
                if float(arr.std()) >= 8.0:
                    return z
        except Exception:
            continue
    return 18


def _fetch_single_png_tile(
    tile: mercantile.Tile,
    cache_dir: Path,
) -> Tuple[int, int, np.ndarray]:
    """Downloads or loads from cache a single 256x256 Esri PNG tile."""
    cached_path = cache_dir / f"rfx_s01_img_tile_z{tile.z}_x{tile.x}_y{tile.y}.png"
    if cached_path.exists() and cached_path.stat().st_size > 1000:
        try:
            img = Image.open(cached_path).convert("RGB")
            return tile.x, tile.y, np.array(img, dtype=np.uint8)
        except Exception:
            pass

    url = ESRI_WORLD_IMAGERY_TPL.format(z=tile.z, y=tile.y, x=tile.x)
    for _ in range(3):
        try:
            resp = requests.get(url, headers=ESRI_HEADERS, timeout=15)
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                img.save(cached_path, format="PNG")
                return tile.x, tile.y, np.array(img, dtype=np.uint8)
        except Exception:
            continue

    return tile.x, tile.y, np.zeros((256, 256, 3), dtype=np.uint8)


def harvest_esri_png_to_geotiff(
    config: EcosystemConfig,
    aoi: ResolvedAOI,
) -> Path:
    """Downloads Esri World Imagery PNG tiles over the AOI, stitches them into a raster canvas,
    georeferences in EPSG:3857, and warps into the metric target CRS (`rfx_s01_ras_ortho_rgb.tif`)."""
    west, south, east, north = aoi.bbox_wgs84
    zoom = detect_best_esri_zoom(aoi.bbox_wgs84, preferred_zoom=config.imagery_zoom)
    tiles = list(mercantile.tiles(west, south, east, north, zoom))

    xs = [t.x for t in tiles]
    ys = [t.y for t in tiles]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    cols = (max_x - min_x) + 1
    rows = (max_y - min_y) + 1
    tile_size = 256
    total_w = cols * tile_size
    total_h = rows * tile_size

    print(
        f"[Section 1 | Esri Ortho] Harvesting {len(tiles)} PNG tiles at Zoom {zoom} "
        f"({total_w}x{total_h} px canvas)..."
    )

    canvas = np.zeros((total_h, total_w, 3), dtype=np.uint8)
    cache_dir = config.db.tile_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    completed = 0
    with ThreadPoolExecutor(max_workers=config.imagery_download_workers) as pool:
        futures = [pool.submit(_fetch_single_png_tile, t, cache_dir) for t in tiles]
        for fut in as_completed(futures):
            tx, ty, tile_np = fut.result()
            px_x = (tx - min_x) * tile_size
            px_y = (ty - min_y) * tile_size
            canvas[px_y : px_y + tile_size, px_x : px_x + tile_size] = tile_np
            completed += 1
            if completed % 250 == 0 or completed == len(tiles):
                print(f"  [Esri Tiles] Assembled {completed}/{len(tiles)} tiles...")

    # Compute Web Mercator (EPSG:3857) bounds and Affine Transform
    ul_bounds = mercantile.xy_bounds(min_x, min_y, zoom)
    lr_bounds = mercantile.xy_bounds(max_x, max_y, zoom)
    src_transform = from_bounds(
        ul_bounds.left, lr_bounds.bottom, lr_bounds.right, ul_bounds.top, total_w, total_h
    )
    src_crs = "EPSG:3857"

    # Warp from EPSG:3857 to unified metric target CRS (e.g., EPSG:32639)
    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs,
        aoi.target_crs,
        total_w,
        total_h,
        left=ul_bounds.left,
        bottom=lr_bounds.bottom,
        right=lr_bounds.right,
        top=ul_bounds.top,
    )

    out_path = config.db.s01_ortho_tif
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[Section 1 | Esri Ortho] Warping & writing georeferenced GeoTIFF ({dst_w}x{dst_h} px) to {out_path}...")

    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=dst_h,
        width=dst_w,
        count=3,
        dtype="uint8",
        crs=aoi.target_crs,
        transform=dst_transform,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        for b in range(3):
            dst_band = np.zeros((dst_h, dst_w), dtype=np.uint8)
            reproject(
                source=canvas[:, :, b],
                destination=dst_band,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=aoi.target_crs,
                resampling=Resampling.bilinear,
            )
            dst.write(dst_band, b + 1)

    print(f"[Section 1 | Esri Ortho] Saved GeoTIFF to: {out_path}")
    return out_path
