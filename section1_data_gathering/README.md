# Section 1: Data Gathering & Preprocessing Engine (`section1_data_gathering/`)

> **RayFlux Solar Intelligence Ecosystem — Independent Spatial Data Factory (Module 1)**  
> Autonomous Universal AOI Resolution, 3D LoD1 Building Footprint & Height Harvesting, $0.50\text{ m}$ Building-Only Synthetic DSM Generation, Auto-Zoom Esri Satellite Orthomosaic Reconstruction, and Atomic Multi-Area PostGIS / GeoPackage / Shapefile / Excel Persistence.

---

## Table of Contents

1. [Purpose & Architectural Role](#1-purpose--architectural-role)
2. [End-to-End Architecture & Data Flow](#2-end-to-end-architecture--data-flow)
3. [Module File Inventory](#3-module-file-inventory)
4. [Inputs: How AOI & Configuration Are Read](#4-inputs-how-aoi--configuration-are-read)
5. [Processing Stages & Scientific Algorithms](#5-processing-stages--scientific-algorithms)
6. [How Outputs Are Saved in the Central Database](#6-how-outputs-are-saved-in-the-central-database)
7. [Complete Output Specifications & Database Schemas](#7-complete-output-specifications--database-schemas)
8. [How Downstream Sections & Users Read Section 1 Data](#8-how-downstream-sections--users-read-section-1-data)
9. [Configuration & CLI Parameters Reference](#9-configuration--cli-parameters-reference)
10. [Execution Manual (Studio UI, Master CLI, Standalone & Python API)](#10-execution-manual-studio-ui-master-cli-standalone--python-api)
11. [Engineering Safeguards, Multi-Area Isolation & Verified Benchmark](#11-engineering-safeguards-multi-area-isolation--verified-benchmark)

---

## 1. Purpose & Architectural Role

`section1_data_gathering` is the **foundational data factory** of the RayFlux Solar Intelligence Ecosystem. Given **any** geographic Area of Interest (AOI) anywhere in the world — supplied as a Shapefile (`.shp`), GeoJSON (`.geojson`), GeoPackage (`.gpkg`), uploaded ZIP archive, hand-drawn polygon in **RayFlux Studio**, or a 4-coordinate Bounding Box — it autonomously harvests, validates, georeferences, warps, and commits the three base datasets consumed by Section 2 (Computer Vision) and Section 3 (Solar Physics):

1. **Validated 3D LoD1 Building Footprints (`s01_building_footprints`)** — Topologically healed polygons with 3D roof heights (`building_height_m`), height variance, estimated floor count, and immutable North-to-South primary keys (`building_id = 1..N`), committed atomically to **PostgreSQL/PostGIS**, **Master GeoPackage (`.gpkg`)**, **ESRI Shapefile (`.shp`)**, and a single **Excel inventory workbook (`.xlsx`)**.
2. **Building-Only Synthetic Digital Surface Model (`rfx_s01_ras_synthetic_dsm.tif`)** — A $0.50\text{ m}$ resolution `float32` elevation raster burned directly from 3D building heights over a clean $0.0\text{ m}$ ground reference plane.
3. **High-Resolution Georeferenced RGB Orthomosaic (`rfx_s01_ras_ortho_rgb.tif`)** — Reconstructed from raw $256 \times 256$ Esri World Imagery PNG tiles with multi-point Zoom 19 / Zoom 18 auto-probing, local tile caching, `EPSG:3857` canvas stitching, and bilinear warping into the unified metric UTM Coordinate Reference System.

---

## 2. End-to-End Architecture & Data Flow

```mermaid
flowchart TD
    subgraph IN ["Inputs: AOI Geometry & Config (config/aoi_resolver.py)"]
        direction LR
        IN_FILE["Vector Boundary<br/>.shp / .geojson / .gpkg / .zip"]
        IN_DRAW["RayFlux Studio Map<br/>Hand-Drawn Polygon"]
        IN_BBOX["WGS84 Bounding Box<br/>(west, south, east, north)"]
        RESOLVER["resolve_case_study_aoi()<br/>Auto UTM Zone EPSG + 15m Edge Buffer"]
        IN_FILE & IN_DRAW & IN_BBOX --> RESOLVER
    end

    subgraph S1 ["Section 1 Processing Tracks (section1_data_gathering/)"]
        direction TB
        subgraph T1 ["Track 1: 3D LoD1 Footprints (footprint_harvester.py)"]
            W1["GET /viewer-session<br/>Auto-Renew WFS Token"] --> W2["0.04° Grid Subdivision<br/>WFS global3D:lod1_global"]
            W2 --> W3["Deduplicate + Metric UTM Warp<br/>make_valid() + Area >= Min Filter"]
            W3 --> W4["Height Normalization + Floor Est.<br/>Deterministic building_id (1..N)"]
        end

        subgraph T2 ["Track 2: Synthetic DSM (synthetic_dsm_builder.py)"]
            D1["0.50 m Metric Grid<br/>over Buffered UTM Extent"] --> D2["Burn building_height_m<br/>Ground = 0.0 m (float32)"]
            D2 --> D3["Tiled LZW GeoTIFF<br/>256x256 Blocks, Predictor=2"]
        end

        subgraph T3 ["Track 3: RGB Orthomosaic (png_to_geotiff_harvester.py)"]
            O1["Zoom 18 or Zoom 19 Selector<br/>3-Point Tile Sharpness Probe"] --> O2["12-Thread PNG Downloader<br/>Resumable Local Tile Cache"]
            O2 --> O3["Stitch EPSG:3857 Canvas<br/>Bilinear Warp to Metric UTM"]
            O3 --> O4["Tiled DEFLATE 3-Band GeoTIFF<br/>uint8 RGB"]
        end
    end

    subgraph DB ["Central Geospatial Database Commit (core_db/database_manager.py)"]
        direction LR
        PG["PostGIS Spatial Table<br/><schema>.s01_building_footprints<br/>(127.0.0.1:5433)"]
        GPKG["Master GeoPackage<br/>rfx_db_master_geodatabase.gpkg"]
        SHP["ESRI Shapefile<br/>rfx_s01_vec_building_footprints.shp"]
        XLS["Single Excel Workbook<br/>rfx_s01_tbl_building_inventory.xlsx"]
        R_DSM["GeoTIFF + SHA-256 Catalog<br/>rfx_s01_ras_synthetic_dsm.tif"]
        R_ORT["GeoTIFF + SHA-256 Catalog<br/>rfx_s01_ras_ortho_rgb.tif"]
        QA["QA/QC 2-Panel Map<br/>rfx_s01_img_base_overview_map.png"]
    end

    RESOLVER --> W1
    RESOLVER --> D1
    RESOLVER --> O1
    W4 -->|3D Polygons + Heights| D2

    W4 ==> PG & GPKG & SHP & XLS
    D3 ==> R_DSM
    O4 ==> R_ORT
    SHP & R_DSM & R_ORT --> QA
```

---

## 3. Module File Inventory

| File | Role |
| :--- | :--- |
| `section1_data_gathering/run_section1.py` | Master orchestrator (`run_section1()`), database commit coordinator, and 2-panel dark-theme QA/QC overview map renderer (`render_s01_overview_map()`). |
| `section1_data_gathering/footprint_harvester.py` | `TUM3DFootprintHarvester` — Automated WFS session token negotiation, $0.04^\circ$ grid tiling, deduplication, topological repair, height/floor extraction, and deterministic `building_id` assignment. |
| `section1_data_gathering/synthetic_dsm_builder.py` | `build_synthetic_dsm_raster()` — Rasterizes 3D building heights onto a $0.50\text{ m}$ `float32` LZW-compressed GeoTIFF over $0.0\text{ m}$ ground. |
| `section1_data_gathering/png_to_geotiff_harvester.py` | `detect_best_esri_zoom()` & `harvest_esri_png_to_geotiff()` — 3-point Zoom 19/18 availability probe, 12-thread PNG tile harvester with local caching, `EPSG:3857` stitching, and metric UTM bilinear warping. |
| `config/aoi_resolver.py` | Universal AOI loader (`.shp`, `.geojson`, `.gpkg`, or 4-tuple BBox), automatic UTM zone EPSG detector, and metric edge buffer calculator. |
| `config/ecosystem_config.py` | `EcosystemConfig`, `DatabasePaths` (default + multi-area `from_root()`), and `PostGISConfig`. |
| `core_db/database_manager.py` | `CentralDatabaseManager` — 4-target atomic vector writer, GeoTIFF SHA-256 cataloger, and transaction audit logger. |

---

## 4. Inputs: How AOI & Configuration Are Read

Section 1 does **not** depend on any upstream database tables — it is the **entry point** that populates the Central Database. Its inputs are:

### 4.1 Area of Interest (`EcosystemConfig.aoi_source`)
Resolved by `config.resolve_aoi()` -> `resolve_case_study_aoi(aoi_source, target_crs, buffer_m)`:
- **Shapefile / GeoJSON / GeoPackage:** Default `data/case_study_aoi/rfx_aoi_boundary.shp`, or per-area boundary `data/areas/<area_id>/rfx_aoi_<area_id>.shp` when registered via RayFlux Studio.
- **WGS84 Bounding Box Tuple:** `(west, south, east, north)` in `EPSG:4326` decimal degrees (via Python API or `--aoi "west,south,east,north"`).
- **Environment Override:** `RFX_AOI_SOURCE` environment variable in `.env`.
- **Automatic UTM Zone Inference:** If `target_crs=None`, `infer_utm_epsg_from_lonlat(lon, lat)` computes:
  $$\text{Zone} = \left(\left\lfloor \frac{\lambda_c + 180^\circ}{6^\circ} \right\rfloor \bmod 60\right) + 1, \qquad \text{EPSG} = \begin{cases} 32600 + \text{Zone} & \phi_c \ge 0^\circ \\ 32700 + \text{Zone} & \phi_c < 0^\circ \end{cases}$$
- **Metric Edge Buffering:** Expands the resolved UTM bounding box by `aoi_buffer_m = 15.0 m` on all 4 sides so border buildings are never clipped during orthophoto cropping (Section 2) or shadow ray-marching (Section 3).

### 4.2 External Data Sources Queried
1. **Global 3D LoD1 Building WFS (`global3D:lod1_global`):** Queried over HTTPS from `tum_wfs_base_url` with automatic `/viewer-session` token negotiation.
2. **Esri World Imagery Tile Server:** `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` (`z = 18` or `z = 19`).

### 4.3 Multi-Area Workspace Resolution
When executed with `--area-id <area_id>` (or via RayFlux Studio), `EcosystemConfig.for_area()` isolates:
- **PostGIS Schema:** `rfx_<area_id>` (default legacy workspace uses `public`).
- **Database Root Folder:** `database/areas/<area_id>/` (default legacy workspace uses `database/`).
- **Tile Cache Directory:** `<db_root>/cache/s01_tiles/`.

---

## 5. Processing Stages & Scientific Algorithms

### 5.1 Stage 1 — 3D LoD1 Building Footprint Harvesting (`footprint_harvester.py`)
1. **Automatic Session Token Management:** Calls `GET /viewer-session`, tracks token expiry (`expiresInSeconds = 900`) and request quota (`maxWfsRequests = 200`), and auto-renews on `HTTP 401/403`.
2. **Safe Grid Subdivision:** Splits the AOI into $0.04^\circ \times 0.04^\circ$ tiles ($\approx 4.4\text{ km} \times 4.4\text{ km}$) to avoid server-side `BBOX_TOO_LARGE` rejections.
3. **Cross-Tile Deduplication & Topological Healing:** Deduplicates edge features by global feature ID (`id` / `ogc_fid`), reprojects to `aoi.target_crs`, repairs invalid rings via `make_valid(geom).buffer(0)`, clips to `aoi.boundary_utm`, and filters out polygons smaller than `min_building_area_m2` (default `50.0 m²`).
4. **3D Attributes & Immutable Primary Key:** Extracts `building_height_m` (clamped $\ge 2.5\text{ m}$, fallback `9.6 m`), `height_variance`, and `num_floors = max(1, round(building_height_m / 3.2))`. Sorts deterministically North-to-South (`centroid_y_utm` descending) then West-to-East (`centroid_x_utm` ascending) and assigns immutable `building_id = 1..N`.

### 5.2 Stage 2 — Building-Only Synthetic DSM (`synthetic_dsm_builder.py`)
Rasterizes validated 3D building polygons directly onto a flat $0.0\text{ m}$ ground reference grid at `dsm_resolution_m = 0.50 m`:
$$W_{\text{DSM}} = \left\lceil \frac{X_{\max} - X_{\min}}{\Delta s} \right\rceil, \qquad H_{\text{DSM}} = \left\lceil \frac{Y_{\max} - Y_{\min}}{\Delta s} \right\rceil$$
$$\text{DSM}(r, c) = \begin{cases} \text{building\_height\_m}_i & \text{if pixel center } (x_c, y_r) \in \mathcal{P}_i \\ 0.0 & \text{otherwise (open ground)} \end{cases}$$
Saved as single-band `float32`, `LZW` (`predictor=2`), $256 \times 256$ internal tiling, `nodata = -9999.0`. This removes LiDAR dependencies and vegetation/terrain noise while preserving exact inter-building 3D shadow casting for Section 3.

### 5.3 Stage 3 — Zoom 18/19 Auto-Probe & PNG-to-GeoTIFF Orthomosaic (`png_to_geotiff_harvester.py`)
1. **User Zoom Selection + 3-Point Sharpness Probe (`detect_best_esri_zoom`):**
   - If the user selects **Zoom 18** (`--zoom 18` or Studio dropdown): downloads directly at Zoom 18 ($\approx 0.48\text{ m/px}$, fast & lightweight).
   - If the user selects **Zoom 19** (`--zoom 19` or default `imagery_zoom = 19`): probes 3 sample tiles across the AOI (`25%`, `50%`, `75%` indices). Zoom 19 is accepted **only** if all probed tiles return `HTTP 200`, byte size `> 3,500 B`, and RGB standard deviation $\sigma \ge 8.0$ (rejecting flat gray `"Map data not yet available"` placeholders). Otherwise, it automatically falls back to **Zoom 18**.
2. **Multi-Threaded Download & Local Cache:** Downloads $256 \times 256$ PNGs with `12` worker threads, caching each tile to `<db_root>/cache/s01_tiles/rfx_s01_img_tile_z{z}_x{x}_y{y}.png` for instant resume on retries.
3. **Stitching & Metric UTM Warp:** Assembles the contiguous `EPSG:3857` RGB canvas, binds exact `mercantile.xy_bounds` affine coordinates, and performs bilinear reprojection (`rasterio.warp.reproject`) into `aoi.target_crs` (`EPSG:32639` or auto UTM) — eliminating Web Mercator's $\approx 52\%$ mid-latitude area distortion. Saved as 3-band `uint8` `DEFLATE`-compressed tiled GeoTIFF.

---

## 6. How Outputs Are Saved in the Central Database

Section 1 never writes unmanaged loose files. All commits pass through `CentralDatabaseManager` (`core_db/database_manager.py`):

### 6.1 4-Target Atomic Vector Commit (`db_mgr.save_vector_dataset`)
```python
db_mgr.save_vector_dataset(
    gdf=footprints_gdf,
    shp_path=config.db.s01_footprints_shp,
    gpkg_layer="s01_building_footprints",
    excel_path=config.db.s01_inventory_xlsx,
)
```
This single atomic call performs **five synchronized actions**:
1. **PostgreSQL / PostGIS (`127.0.0.1:5433`, DB `rayflux_spatial_db`):**
   - Auto-starts the local PostGIS cluster if offline (`ensure_postgis_cluster_running()`).
   - Ensures `CREATE EXTENSION IF NOT EXISTS postgis` and `CREATE SCHEMA IF NOT EXISTS "<schema>"`.
   - Sorts by `building_id`, enforces `target_crs`, and writes `<schema>.s01_building_footprints` (`if_exists="replace"`, spatial index enabled).
2. **Master GeoPackage:** Writes full-schema layer `s01_building_footprints` to `<db_root>/core/rfx_db_master_geodatabase.gpkg`.
3. **ESRI Shapefile:** Maps long column names via `SHP_COLUMN_MAP` to deterministic $\le 10$-character dBase fields and writes `<db_root>/shapefiles/s01_base/rfx_s01_vec_building_footprints.shp` (`UTF-8`).
4. **Single Excel Workbook (`.xlsx`):** Drops `geometry` and writes `<db_root>/tables/s01_base/rfx_s01_tbl_building_inventory.xlsx` via `openpyxl` (no duplicate `.csv` files are generated).
5. **Catalog & Audit Provenance:** Computes SHA-256 checksum, records portable project-relative POSIX paths, feature count, CRS, bounds, and `postgis_synced` status in `<db_root>/core/rfx_db_asset_catalog.json`, and appends a timestamped `WRITE_POSTGIS` / `WRITE_VECTOR` entry to `<db_root>/core/rfx_db_transaction_audit.log`.

### 6.2 GeoTIFF Raster Registration (`db_mgr.register_raster`)
```python
db_mgr.register_raster(dsm_path, "s01_synthetic_dsm")
db_mgr.register_raster(ortho_path, "s01_ortho_rgb")
```
Opens each GeoTIFF with `rasterio`, validates readable dimensions, bands, dtype, CRS, pixel resolution, geographic bounds, computes its SHA-256 hash, registers it in `rfx_db_asset_catalog.json`, and logs `WRITE_RASTER` in `rfx_db_transaction_audit.log`.

---

## 7. Complete Output Specifications & Database Schemas

### 7.1 Vector & Tabular Schema (`<schema>.s01_building_footprints`)

| PostGIS / GPKG / Excel Column | Shapefile Field ($\le 10$ chars) | Data Type | Units | Description |
| :--- | :--- | :--- | :--- | :--- |
| `building_id` | `bldg_id` | `int64` | — | **Immutable Primary Key ($1 \dots N$)** sorted North-to-South, West-to-East. |
| `source_feature_id` | `src_id` | `str` | — | Original Global 3D LoD1 WFS feature identifier. |
| `gross_area_m2` | `gross_area` | `float64` | $\text{m}^2$ | Topologically valid 2D building footprint area in metric UTM. |
| `building_height_m` | `height_m` | `float64` | $\text{m}$ | 3D structural roof height above ground ($\ge 2.5\text{ m}$). |
| `height_variance` | `height_var` | `float64` | $\text{m}^2$ | Roof height variance from 3D LoD1 model (`0.0` if flat/uniform). |
| `num_floors` | `floors` | `int32` | count | Estimated building stories ($\max(1, \text{round}(\text{height\_m}/3.2))$). |
| `centroid_x_utm` | `cx_utm` | `float64` | $\text{m}$ | Building centroid Easting in `target_crs`. |
| `centroid_y_utm` | `cy_utm` | `float64` | $\text{m}$ | Building centroid Northing in `target_crs`. |
| `geometry` | `geometry` | `Polygon` / `MultiPolygon` | $\text{m}$ | Validated 2D building footprint polygon in `target_crs`. |

### 7.2 Standardized File Assets (Relative to `<db_root>`)

| Catalog Key | Standardized Path | Format & Technical Specs |
| :--- | :--- | :--- |
| `s01_building_footprints` | `shapefiles/s01_base/rfx_s01_vec_building_footprints.shp` | PostGIS `<schema>.s01_building_footprints` + Master GPKG + `.shp` |
| *(inventory table)* | `tables/s01_base/rfx_s01_tbl_building_inventory.xlsx` | Single `.xlsx` workbook (attribute table without geometry) |
| `s01_synthetic_dsm` | `rasters/s01_base/rfx_s01_ras_synthetic_dsm.tif` | 1-band `float32`, $0.50\text{ m}$, `LZW` (`predictor=2`), $256\times256$ tiled, `nodata=-9999.0` |
| `s01_ortho_rgb` | `rasters/s01_base/rfx_s01_ras_ortho_rgb.tif` | 3-band `uint8` RGB, $\approx 0.25\text{–}0.48\text{ m/px}$, `DEFLATE`, $256\times256$ tiled |
| *(QA overview map)* | `maps/s01_base/rfx_s01_img_base_overview_map.png` | 2-panel dark-theme verification figure (RGB + Footprints | Synthetic DSM) |
| *(PNG tile cache)* | `cache/s01_tiles/rfx_s01_img_tile_z{z}_x{x}_y{y}.png` | Resumable raw $256\times256$ Esri PNG tiles (git-ignored) |

---

## 8. How Downstream Sections & Users Read Section 1 Data

### 8.1 Programmatic Read via `CentralDatabaseManager` (Used by Sections 2 & 3)
```python
from config.ecosystem_config import EcosystemConfig
from core_db.database_manager import CentralDatabaseManager
import rasterio

cfg = EcosystemConfig()  # or EcosystemConfig.for_area(...)
db_mgr = CentralDatabaseManager(cfg)

# Vector read hierarchy: PostGIS primary -> Master GPKG fallback -> Shapefile fallback
# Automatically restores full column names via INV_SHP_COLUMN_MAP & enforces target_crs
footprints_gdf = db_mgr.load_vector_dataset(
    cfg.db.s01_footprints_shp,
    gpkg_layer="s01_building_footprints",
)

# Raster reads (direct windowed or full reads)
with rasterio.open(cfg.db.s01_synthetic_dsm_tif) as dsm_src:
    dsm_crs, dsm_res = dsm_src.crs, dsm_src.res
```

### 8.2 Direct PostGIS SQL Query Example
```python
import geopandas as gpd
from sqlalchemy import create_engine

engine = create_engine("postgresql+psycopg2://rayflux_admin:RayFlux_2026_Pass@127.0.0.1:5433/rayflux_spatial_db")
gdf = gpd.read_postgis(
    'SELECT building_id, gross_area_m2, building_height_m, num_floors, geometry '
    'FROM "public"."s01_building_footprints" ORDER BY building_id',
    con=engine,
    geom_col="geometry",
)
```

---

## 9. Configuration & CLI Parameters Reference

| Parameter (`EcosystemConfig`) | CLI Flag (`run_ecosystem.py`) | Default | Description |
| :--- | :--- | :--- | :--- |
| `aoi_source` | `--aoi` | `data/case_study_aoi/rfx_aoi_boundary.shp` | Path to `.shp`/`.geojson`/`.gpkg` or `"west,south,east,north"` bbox. |
| `aoi_buffer_m` | — | `15.0` | Metric buffer ($\text{m}$) around AOI before DSM/ortho extraction. |
| `target_crs` | — | `"EPSG:32639"` (or `None` auto-UTM) | Unified metric UTM CRS for all vector and raster outputs. |
| `min_building_area_m2` | `--min-area` | `50.0` | Minimum footprint area ($\text{m}^2$) to retain. |
| `default_building_height_m` | — | `9.6` | Fallback height ($\text{m}$) if WFS height is null. |
| `tum_grid_step_deg` | — | `0.04` | WFS grid tile size in decimal degrees ($\approx 4.4\text{ km}$). |
| `imagery_zoom` | `--zoom` (`18` \| `19`) | `19` | Target Esri zoom (`19` auto-falls back to `18` if unavailable/blank). |
| `imagery_download_workers` | — | `12` | Concurrent threads for PNG tile downloads. |
| `dsm_resolution_m` | `--dsm-res` | `0.50` | Pixel size ($\text{m}$) of the Synthetic DSM GeoTIFF. |

---

## 10. Execution Manual (Studio UI, Master CLI, Standalone & Python API)

```bash
# 1. Recommended: Launch RayFlux Studio Control Center (draw/upload AOI, pick Zoom 18/19, run S1)
.venv/Scripts/python.exe rayflux_studio.py

# 2. Master CLI Orchestrator (default workspace or isolated multi-area workspace)
.venv/Scripts/python.exe run_ecosystem.py --section 1 --aoi data/case_study_aoi/rfx_aoi_boundary.shp --zoom 18
.venv/Scripts/python.exe run_ecosystem.py --section 1 --area-id my_zone --zoom 19

# 3. Standalone Section 1 Execution
.venv/Scripts/python.exe -m section1_data_gathering.run_section1
```

**Python API:**
```python
from config.ecosystem_config import EcosystemConfig, DATA_INPUT_DIR
from section1_data_gathering.run_section1 import run_section1

# Pass a custom EcosystemConfig directly
cfg = EcosystemConfig(aoi_source=DATA_INPUT_DIR / "rfx_aoi_boundary.shp", imagery_zoom=18)
run_section1(config=cfg)

# Or pass a quick AOI override (Path, str, or WGS84 bbox tuple)
run_section1(aoi_override=(50.3558, 35.7218, 50.3598, 35.7245))
```

---

## 11. Engineering Safeguards, Multi-Area Isolation & Verified Benchmark

- **Automatic WFS Token Renewal:** Transparently refreshes expired `/viewer-session` tokens on `HTTP 401/403` without aborting multi-tile harvests.
- **3-Point Zoom 19 Guard:** Prevents corrupt gray placeholder mosaics by checking tile byte size and RGB variance across 3 AOI sample positions before committing to Zoom 19.
- **Resumable Tile Cache & PostGIS Auto-Recovery:** Cached PNG tiles speed up re-runs, and `get_postgis_engine()` automatically starts the local PostgreSQL 16 + PostGIS 3.4 cluster (`127.0.0.1:5433`) if Windows restarted.
- **Selective Re-Run Cleanup:** In RayFlux Studio, re-running Section 1 on an already-processed area triggers a preflight warning modal that lets the user surgically purge Section 1 (and optionally S2/S3) tables and rasters before re-executing.

### Verified Case Study Benchmark (`EPSG:32639`, `100%` PostGIS Synced)
| Metric | Verified Result |
| :--- | :--- |
| **3D Buildings Harvested** | `3,962` (`public.s01_building_footprints`) |
| **Synthetic DSM (`0.50 m`)** | `13,486 × 8,274 px` (`float32`, LZW tiled) |
| **RGB Orthomosaic (`0.4847 m`)** | `14,415 × 8,778 px` (`uint8` 3-band RGB, DEFLATE tiled) |
| **QA/QC Map** | `rfx_s01_img_base_overview_map.png` (verified sub-meter footprint-to-imagery alignment) |
