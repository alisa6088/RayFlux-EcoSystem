# Section 1: Data Gathering & Preprocessing Engine (`section1_data_gathering`)
## Comprehensive 0-to-100 Technical Documentation & Engineering Reference

> **Module Role in the RayFlux Ecosystem:**  
> `section1_data_gathering` is the **Independent Data Factory (Module 1)** of the RayFlux Solar Intelligence Ecosystem. Given **any** Case Study Area of Interest (a Shapefile, a GeoJSON/GeoPackage, or a 4-coordinate Bounding Box), it autonomously harvests, cleans, georeferences, warps, and commits the three foundational spatial assets required by downstream computer vision and solar physics engines:
> 1. **Validated 3D Building Footprints (`s01_building_footprints`)** — Stored in **PostgreSQL/PostGIS**, **Master GeoPackage (`.gpkg`)**, **ESRI Shapefile (`.shp`)**, and **Excel/CSV (`.xlsx` / `.csv`)**.
> 2. **Building-Only Synthetic Digital Surface Model (`rfx_s01_ras_synthetic_dsm.tif`)** — A $0.50\text{ m}$ resolution `float32` elevation raster burned directly from 3D building heights with $0.0\text{ m}$ ground level.
> 3. **High-Resolution Georeferenced Optical Orthomosaic (`rfx_s01_ras_ortho_rgb.tif`)** — Built by harvesting raw $256 \times 256$ satellite PNG tiles, stitching them into a continuous canvas, injecting spatial bounds, and warping to the unified metric UTM Coordinate Reference System.

---

## Table of Contents

1. [End-to-End Architecture & Data Flow](#1-end-to-end-architecture--data-flow)
2. [Module Directory & File Inventory](#2-module-directory--file-inventory)
3. [Stage 0: Universal Case Study AOI Resolution (`config/aoi_resolver.py`)](#3-stage-0-universal-case-study-aoi-resolution-configaoi_resolverpy)
4. [Stage 1: 3D LoD1 Building Footprint Harvesting (`footprint_harvester.py`)](#4-stage-1-3d-lod1-building-footprint-harvesting-footprint_harvesterpy)
5. [Stage 2: Building-Only Synthetic DSM Generation (`synthetic_dsm_builder.py`)](#5-stage-2-building-only-synthetic-dsm-generation-synthetic_dsm_builderpy)
6. [Stage 3: High-Resolution PNG Tile Harvesting & GeoTIFF Creation (`png_to_geotiff_harvester.py`)](#6-stage-3-high-resolution-png-tile-harvesting--geotiff-creation-png_to_geotiff_harvesterpy)
7. [Stage 4: Central Database & PostGIS Persistence (`core_db/`)](#7-stage-4-central-database--postgis-persistence-core_db)
8. [Stage 5: Automated QA/QC Overview Map Rendering](#8-stage-5-automated-qaqc-overview-map-rendering)
9. [Complete Output Specifications & Database Schemas](#9-complete-output-specifications--database-schemas)
10. [Configuration Parameters Reference](#10-configuration-parameters-reference)
11. [Execution Manual (CLI & Python API)](#11-execution-manual-cli--python-api)
12. [Engineering Safeguards & Troubleshooting](#12-engineering-safeguards--troubleshooting)

---

## 1. End-to-End Architecture & Data Flow

```mermaid
flowchart TD
    %% INPUT AOI
    subgraph AOI_IN ["Stage 0: Universal Case Study AOI Input (config/aoi_resolver.py)"]
        direction LR
        IN_SHP["Shapefile (.shp)<br/>data/case_study_aoi/"]
        IN_GEO["GeoJSON / GPKG<br/>(.geojson / .gpkg)"]
        IN_BBOX["Bounding Box Tuple<br/>(west, south, east, north)"]
        RESOLVER["resolve_case_study_aoi()<br/>• Auto-Detects UTM Zone EPSG<br/>• Computes WGS84 & Metric Bounds<br/>• Applies Metric Edge Buffer"]
        IN_SHP & IN_GEO & IN_BBOX --> RESOLVER
    end

    %% STAGE 1, 2, 3
    subgraph S1_CORE ["Section 1 Processing Pipelines (section1_data_gathering/)"]
        direction TB
        
        subgraph TRACK_FP ["Track 1: 3D Building Footprints (footprint_harvester.py)"]
            T_TOK["Auto-Negotiate WFS Token<br/>GET /viewer-session"] --> T_GRID["Subdivide AOI into Safe Grid<br/>(Δ = 0.04° Tiles)"]
            T_GRID --> T_WFS["Query Global 3D LoD1 WFS<br/>(typeNames=global3D:lod1_global)"]
            T_WFS --> T_CLEAN["Deduplicate Edge Buildings,<br/>Reproject to Metric UTM & Heal Topology"]
            T_CLEAN --> T_ID["Filter Area ≥ Min Threshold &<br/>Assign Immutable building_id (1..N)"]
        end

        subgraph TRACK_DSM ["Track 2: Synthetic DSM (synthetic_dsm_builder.py)"]
            D_GRID["Construct 0.50m Metric Grid<br/>over Resolved AOI Bounds"] --> D_BURN["Burn 3D building_height_m<br/>(Ground = 0.0m, Float32)"]
            D_BURN --> D_TIF["Write Tiled LZW GeoTIFF<br/>(256x256 Blocks, Predictor=2)"]
        end

        subgraph TRACK_IMG ["Track 3: PNG-to-GeoTIFF Orthomosaic (png_to_geotiff_harvester.py)"]
            I_ZOOM["Auto-Probe Native Max Zoom<br/>(Reject Blank Placeholder Tiles)"] --> I_DL["Multi-Threaded PNG Tile Harvester<br/>(12 Workers + Local PNG Cache)"]
            I_DL --> I_STITCH["Stitch RGB Canvas & Compute<br/>EPSG:3857 Affine Transform"]
            I_STITCH --> I_WARP["Bilinear Warp to Metric UTM CRS<br/>(Tiled DEFLATE GeoTIFF)"]
        end
    end

    %% DATABASE COMMIT
    subgraph DB_OUT ["Stage 4: Central Geospatial Database Commit (database/ & PostGIS)"]
        direction LR
        OUT_PG["PostgreSQL / PostGIS<br/>Table: public.s01_building_footprints<br/>(127.0.0.1:5433)"]
        OUT_SHP["Vector Shapefile & GPKG<br/>rfx_s01_vec_building_footprints.shp<br/>rfx_db_master_geodatabase.gpkg"]
        OUT_XLS["Tabular Inventory<br/>rfx_s01_tbl_building_inventory.xlsx<br/>& .csv"]
        OUT_DSM["Synthetic DSM Raster<br/>rfx_s01_ras_synthetic_dsm.tif"]
        OUT_ORT["High-Res Ortho Raster<br/>rfx_s01_ras_ortho_rgb.tif"]
        OUT_MAP["QA/QC Overview Map<br/>rfx_s01_img_base_overview_map.png"]
    end

    RESOLVER --> T_TOK
    RESOLVER --> D_GRID
    RESOLVER --> I_ZOOM
    T_ID -->|3D Polygons + building_height_m| D_BURN

    T_ID ==> OUT_PG & OUT_SHP & OUT_XLS
    D_TIF ==> OUT_DSM
    I_WARP ==> OUT_ORT
    OUT_SHP & OUT_DSM & OUT_ORT --> OUT_MAP
```

---

## 2. Module Directory & File Inventory

```text
solar_ecosystem/
│
├── data/
│   └── case_study_aoi/                            # Input folder for Case Study boundary files (rfx_aoi_boundary.shp / .geojson)
│
├── config/
│   ├── aoi_resolver.py                            # Stage 0: Universal AOI parser, UTM zone calculator & buffer engine
│   └── ecosystem_config.py                        # Master parameters, PostGIS config & standardized rfx_* paths
│
├── core_db/
│   ├── env_guard.py                               # PROJ_LIB / GDAL isolation guard
│   ├── init_postgis_cluster.py                    # Dedicated PostgreSQL + PostGIS cluster initializer
│   └── database_manager.py                        # Atomic writer/reader for PostGIS, GPKG, .shp, .tif, .xlsx & catalog
│
└── section1_data_gathering/
    ├── __init__.py                                # Package exports
    ├── README.md                                  # This comprehensive documentation manual
    ├── footprint_harvester.py                     # Stage 1: Automated 3D LoD1 WFS building & height harvester
    ├── synthetic_dsm_builder.py                   # Stage 2: 0.50m building-only Synthetic DSM rasterizer
    ├── png_to_geotiff_harvester.py                # Stage 3: High-res Esri PNG tile downloader, stitcher & UTM warp
    └── run_section1.py                            # Master Section 1 CLI entrypoint & QA/QC overview map renderer
```

---

## 3. Stage 0: Universal Case Study AOI Resolution (`config/aoi_resolver.py`)

### 3.1 Supported Input Formats
The ecosystem is completely region-agnostic. `EcosystemConfig.aoi_source` accepts any of three input types:
1. **Vector Shapefile (`.shp`):** e.g., `data/case_study_aoi/study_zone.shp` (can be either a single boundary polygon or an existing collection of building polygons whose outer envelope defines the study zone).
2. **GeoJSON or GeoPackage (`.geojson`, `.json`, `.gpkg`):** e.g., `data/case_study_aoi/study_zone.geojson`.
3. **Bounding Box Tuple/List:** `(west, south, east, north)` in `EPSG:4326` decimal degrees (or `(xmin, ymin, xmax, ymax)` in metric UTM meters).

### 3.2 Automatic UTM Zone Inference
When `target_crs` is not manually overridden, `infer_utm_epsg_from_lonlat(lon, lat)` automatically determines the exact WGS 84 metric UTM Zone from the AOI centroid $(\lambda_c, \phi_c)$:

$$\text{Zone} = \left(\left\lfloor \frac{\lambda_c + 180^\circ}{6^\circ} \right\rfloor \bmod 60\right) + 1, \qquad \text{EPSG} = \begin{cases} 32600 + \text{Zone} & \text{if } \phi_c \ge 0^\circ \text{ (Northern Hemisphere)} \\ 32700 + \text{Zone} & \text{if } \phi_c < 0^\circ \text{ (Southern Hemisphere)} \end{cases}$$

### 3.3 Edge Buffering (`aoi_buffer_m`)
To prevent boundary buildings from having their cast shadows or roof edges clipped at the border of the raster, `resolve_case_study_aoi()` expands the metric UTM bounding box by `aoi_buffer_m = 15.0` meters in all four cardinal directions before harvesting imagery and burning the Synthetic DSM.

---

## 4. Stage 1: 3D LoD1 Building Footprint Harvesting (`footprint_harvester.py`)

### 4.1 Why the Global 3D LoD1 WFS Database Is Used
Standard 2D cadastral maps (such as OpenStreetMap or raw Overture polygons) frequently lack building height attributes (`height = 0` or `NULL`), which makes 3D shadow ray-tracing impossible without airborne LiDAR. `TUM3DFootprintHarvester` queries the **Global 3D LoD1 Building Database (`global3D:lod1_global`)**, which provides both the 2D building footprint polygon and photogrammetrically/AI-derived 3D roof height (`height`) and height variance (`var`).

### 4.2 Step-by-Step Harvesting Algorithm
1. **Automatic Session Token Negotiation (`_obtain_viewer_session_token`):**
   * The WFS server requires a time-limited `viewerSession` token (`expiresInSeconds = 900`, `maxWfsRequests = 200`).
   * `TUM3DFootprintHarvester` automatically sends a `GET` request to `/viewer-session`, extracts the active token, tracks request counts, and transparently refreshes the token before expiration or upon any `HTTP 401/403` response.
2. **Safe Grid Subdivision (`tum_grid_step_deg = 0.04`):**
   * Because the WFS server rejects oversized bounding boxes (`BBOX_TOO_LARGE` above $\approx 0.076^\circ$), the AOI bounding box $(\lambda_{\min}, \phi_{\min}, \lambda_{\max}, \phi_{\max})$ is partitioned into a regular grid of $0.04^\circ \times 0.04^\circ$ tiles ($\approx 4.4\text{ km} \times 4.4\text{ km}$ per tile).
3. **Cross-Tile Deduplication:**
   * Buildings intersecting internal grid lines are returned in both adjacent tiles. The harvester deduplicates all extracted features using their unique global feature identifier (`id` / `ogc_fid`).
4. **Metric Reprojection & Topological Healing:**
   * All features are reprojected from `EPSG:4326` to `aoi.target_crs` (`EPSG:32639`).
   * Every geometry is repaired via `make_valid(geom).buffer(0)` to eliminate self-intersections, bowtie rings, and degenerate vertices.
   * Only `Polygon` and `MultiPolygon` features intersecting `aoi.boundary_utm` with `gross_area_m2 >= min_building_area_m2` ($50.0\text{ m}^2$) are retained.
5. **Height Standardization & Floor Estimation:**
   * `building_height_m` is extracted from `height`, clipped to a physical minimum of $2.5\text{ m}$ (falling back to `default_building_height_m = 9.6` only if null).
   * `height_variance` is extracted from `var`.
   * `num_floors` is computed as $\max\big(1,\; \text{round}(\text{building\_height\_m} / 3.2)\big)$.
6. **Deterministic Spatial Sorting & Immutable `building_id` Assignment:**
   * Buildings are sorted deterministically by centroid (`centroid_y_utm` descending North-to-South, `centroid_x_utm` ascending West-to-East) and assigned an immutable integer primary key `building_id` $\in \{1, 2, \dots, N\}$.

---

## 5. Stage 2: Building-Only Synthetic DSM Generation (`synthetic_dsm_builder.py`)

### 5.1 Scientific Rationale: Why a Building-Only Synthetic DSM?
In traditional solar GIS workflows, a Digital Surface Model (DSM) is derived from airborne LiDAR point clouds (`.las`). However:
1. High-density airborne LiDAR is unavailable or restricted in most developing regions and industrial zones.
2. Raw LiDAR DSMs include terrain slope and street trees, requiring $10+$ complex scripts for Digital Terrain Model (DTM) subtraction ($n\text{DSM} = \text{DSM} - \text{DTM}$) and vegetation classification.

By rasterizing the validated 3D LoD1 building heights directly onto a flat $0.0\text{ m}$ ground reference grid at $0.50\text{ m}$ resolution, `build_synthetic_dsm_raster()` produces a **noise-free Building-Only Synthetic DSM** that accurately models mutual inter-building shadow casting in Section 3 without requiring LiDAR or vegetation filtering.

### 5.2 Mathematical Grid Formulation
Given the metric AOI bounding box $(X_{\min}, Y_{\min}, X_{\max}, Y_{\max})$ and pixel resolution $\Delta s = 0.50\text{ m}$:

$$W_{\text{DSM}} = \left\lceil \frac{X_{\max} - X_{\min}}{\Delta s} \right\rceil, \qquad H_{\text{DSM}} = \left\lceil \frac{Y_{\max} - Y_{\min}}{\Delta s} \right\rceil$$

The upper-left affine transformation matrix $\mathbf{T}_{\text{DSM}}$ is:

$$\begin{bmatrix} x_{\text{utm}} \\ y_{\text{utm}} \\ 1 \end{bmatrix} = \begin{bmatrix} \Delta s & 0 & X_{\min} \\ 0 & -\Delta s & Y_{\max} \\ 0 & 0 & 1 \end{bmatrix} \begin{bmatrix} c \\ r \\ 1 \end{bmatrix}$$

Each pixel $(r, c)$ is assigned:

$$\text{DSM}(r, c) = \begin{cases} \text{building\_height\_m}_i & \text{if pixel center } (x_c, y_r) \in \mathcal{P}_i \\ 0.0 & \text{otherwise (streets / open ground)} \end{cases}$$

The array is written to `rfx_s01_ras_synthetic_dsm.tif` as a single-band `float32` GeoTIFF with `LZW` compression, horizontal differencing (`predictor=2`), `256x256` internal tiling, and `nodata = -9999.0`.

---

## 6. Stage 3: High-Resolution PNG Tile Harvesting & GeoTIFF Creation (`png_to_geotiff_harvester.py`)

### 6.1 Why PNG Tiles Are Converted to GeoTIFF
Global satellite imagery providers (Esri World Imagery) do not serve downloadable pre-warped GeoTIFFs at sub-meter zoom levels ($z \in \{18, 19, 20\}$). Instead, imagery is streamed as unprojected $256 \times 256$ RGB PNG tiles over a Spherical Web Mercator slippy-map grid (`EPSG:3857`). `png_to_geotiff_harvester.py` reconstructs a metric-accurate GeoTIFF from these raw PNG tiles in four stages:

1. **Automatic Native Max-Zoom Probe (`detect_best_esri_zoom`):**
   * In dense city centers, Esri serves imagery up to Zoom 19 ($\approx 0.298\text{ m/px}$), whereas in outer industrial parks, Zoom 19 returns a $2,521\text{-byte}$ flat gray placeholder tile (`"Map data not yet available"`, pixel $\sigma \approx 5.3$).
   * Before starting a bulk download, `detect_best_esri_zoom()` probes the center tile of the AOI starting from `preferred_zoom = 19` downward, selecting the highest zoom level where file size $> 3,500\text{ bytes}$ and RGB pixel standard deviation $\sigma \ge 8.0$ (e.g., automatically selecting Zoom 18 when Zoom 19 is a placeholder).
2. **Multi-Threaded Downloading & Local PNG Tile Caching:**
   * Tile coordinates $(x, y, z)$ covering `aoi.bbox_wgs84` are enumerated via `mercantile.tiles(west, south, east, north, zoom)`.
   * A `ThreadPoolExecutor` (`imagery_download_workers = 12`) downloads tiles concurrently from:
     `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`
   * Every downloaded PNG is cached to `database/cache/s01_tiles/rfx_s01_img_tile_z{z}_x{x}_y{y}.png`. Subsequent runs load directly from the local cache in milliseconds.
3. **Canvas Assembly & `EPSG:3857` Georeferencing:**
   * All $256 \times 256$ PNG arrays are placed into a contiguous RGB canvas of size:
     $$W_{3857} = (x_{\max} - x_{\min} + 1) \times 256, \qquad H_{3857} = (y_{\max} - y_{\min} + 1) \times 256$$
   * Exact Web Mercator outer bounds $(X_{\text{left}}, Y_{\text{bottom}}, X_{\text{right}}, Y_{\text{top}})$ are computed via `mercantile.xy_bounds` and bound to a 6-parameter Affine transform via `rasterio.transform.from_bounds`.
4. **Metric UTM Warping (`EPSG:3857` $\rightarrow$ `EPSG:32639`):**
   * Because Web Mercator (`EPSG:3857`) distorts true ground area by $\frac{1}{\cos^2(\phi)} \approx +52\%$ at $\phi \approx 35.7^\circ\text{N}$, the 3-band canvas is warped via bilinear resampling (`rasterio.warp.reproject`) into `aoi.target_crs` (`EPSG:32639`) and saved as a tiled, `DEFLATE`-compressed 3-band GeoTIFF (`rfx_s01_ras_ortho_rgb.tif`).

---

## 7. Stage 4: Central Database & PostGIS Persistence (`core_db/`)

### 7.1 Dedicated PostgreSQL 16.8 + PostGIS 3.4.2 Cluster (`init_postgis_cluster.py`)
All vector layers generated by the ecosystem are persisted in a dedicated **PostgreSQL + PostGIS** spatial database cluster managed automatically by `core_db/init_postgis_cluster.py` and `core_db/database_manager.py`:

| Parameter | Value | Description |
| :--- | :--- | :--- |
| **PostgreSQL Binaries** | Auto-discovered (`RFX_PG_BIN_DIR` or system `PATH`) | Local PostgreSQL 16.8 + PostGIS 3.4.2 engine binaries |
| **Cluster Data Directory**| `database/postgis_cluster` | Self-contained database cluster owned by the project |
| **Host / Port** | `127.0.0.1:5433` | Dedicated port isolated from any default port 5432 instance |
| **Database Name** | `rayflux_spatial_db` | Spatial database with `CREATE EXTENSION postgis;` enabled |
| **Schema** | `public` | Default spatial schema |
| **Username** | `rayflux_admin` | Dedicated superuser account |
| **Password** | `RayFlux_2026_Pass` | Stored in `.env` and `database/core/rfx_db_postgis_credentials.json` |

### 7.2 4-Target Atomic Vector Commit (`save_vector_dataset`)
Whenever Section 1 commits `footprints_gdf`, `CentralDatabaseManager.save_vector_dataset()` writes the dataset to **four synchronized targets**:
1. **PostGIS Spatial Table:** `public.s01_building_footprints` (with GiST spatial index on `geometry`).
2. **Master GeoPackage:** Layer `s01_building_footprints` inside `database/core/rfx_db_master_geodatabase.gpkg`.
3. **ESRI Shapefile:** `database/shapefiles/s01_base/rfx_s01_vec_building_footprints.shp` (with deterministic $\le 10$-character field names).
4. **Excel & CSV Inventory:** `database/tables/s01_base/rfx_s01_tbl_building_inventory.xlsx` & `.csv`.

---

## 8. Stage 5: Automated QA/QC Overview Map Rendering

At the end of `run_section1.py`, `render_s01_overview_map()` generates a high-resolution, 2-panel dark-theme verification figure saved to:
* `database/maps/s01_base/rfx_s01_img_base_overview_map.png`
  * **Left Panel:** The metric-warped Esri RGB Orthomosaic (`rfx_s01_ras_ortho_rgb.tif`) overlaid with the cyan vector boundaries of all validated 3D building footprints (`rfx_s01_vec_building_footprints.shp`), verifying sub-meter spatial alignment between the imagery and footprints.
  * **Right Panel:** The $0.50\text{ m}$ Building-Only Synthetic DSM (`rfx_s01_ras_synthetic_dsm.tif`) rendered with a `magma` elevation colorbar ($\text{m}$), verifying height rasterization and $0.0\text{ m}$ ground normalization.

---

## 9. Complete Output Specifications & Database Schemas

### 9.1 Vector & Tabular Schema (`s01_building_footprints`)
| PostGIS / GPKG / Excel Column | Shapefile Field ($\le 10$ chars) | Data Type | Units | Description |
| :--- | :--- | :--- | :--- | :--- |
| `building_id` | `bldg_id` | `int64` | — | **Immutable Primary Key ($1 \dots N$)** sorted North-to-South, West-to-East. |
| `source_feature_id` | `src_id` | `str` | — | Original WFS feature ID (`id` / `ogc_fid`). |
| `gross_area_m2` | `gross_area` | `float64` | $\text{m}^2$ | Validated 2D building footprint area in metric UTM coordinates. |
| `building_height_m` | `height_m` | `float64` | $\text{m}$ | 3D structural roof height above ground ($\ge 2.5\text{ m}$). |
| `height_variance` | `height_var` | `float64` | $\text{m}^2$ | Roof height variance from 3D model (`0.0` if flat/uniform). |
| `num_floors` | `floors` | `int32` | count | Estimated number of building stories ($\max(1, \text{round}(\text{height\_m}/3.2))$). |
| `centroid_x_utm` | `cx_utm` | `float64` | $\text{m}$ | Building centroid Easting in `target_crs` (`EPSG:32639`). |
| `centroid_y_utm` | `cy_utm` | `float64` | $\text{m}$ | Building centroid Northing in `target_crs` (`EPSG:32639`). |
| `geometry` | `geometry` | `Polygon` / `MultiPolygon` | $\text{m}$ | Topologically valid 2D building footprint polygon (`EPSG:32639`). |

### 9.2 Raster Output Specifications
| Asset Key | Standardized Path | Bands & Dtype | Resolution | Compression & Tiling | NoData |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `s01_synthetic_dsm` | `database/rasters/s01_base/rfx_s01_ras_synthetic_dsm.tif` | 1-Band `float32` | $0.50\text{ m} \times 0.50\text{ m}$ | `LZW` (`predictor=2`), $256 \times 256$ tiled | `-9999.0` |
| `s01_ortho_rgb` | `database/rasters/s01_base/rfx_s01_ras_ortho_rgb.tif` | 3-Band `uint8` (RGB) | $\approx 0.30\text{ m} - 0.48\text{ m}$ | `DEFLATE`, $256 \times 256$ tiled | `None` |

---

## 10. Configuration Parameters Reference

Configured in `config/ecosystem_config.py` (`EcosystemConfig`):

| Parameter | Default Value | Description |
| :--- | :--- | :--- |
| `aoi_source` | `DATA_INPUT_DIR / "rfx_aoi_boundary.shp"` | Relative path to case study `.shp`, `.geojson`, `.gpkg`, or `(west, south, east, north)` tuple. |
| `aoi_buffer_m` | `15.0` | Metric buffer ($\text{m}$) added around the AOI extent before raster/tile extraction. |
| `target_crs` | `"EPSG:32639"` | Unified metric UTM CRS (or `None` to auto-detect UTM zone from AOI centroid). |
| `min_building_area_m2` | `50.0` | Minimum footprint area ($\text{m}^2$) required to retain a building. |
| `default_building_height_m` | `9.6` | Fallback height ($\text{m}$) if a building record has a null height attribute. |
| `tum_wfs_base_url` | `"https://tubvsig-so2sat-vm1.srv.mwn.de"` | Base URL for the Global 3D LoD1 WFS server and `/viewer-session` endpoint. |
| `tum_grid_step_deg` | `0.04` | WFS download grid cell size in decimal degrees ($\approx 4.4\text{ km}$). |
| `imagery_provider` | `"esri"` | High-resolution imagery source (`Esri World Imagery`). |
| `imagery_zoom` | `19` | Target slippy-map zoom level (auto-steps down via `detect_best_esri_zoom()` if placeholder). |
| `imagery_download_workers` | `12` | Concurrent HTTP threads for downloading PNG tiles. |
| `dsm_resolution_m` | `0.50` | Pixel size ($\text{m}$) of the output Synthetic DSM raster. |

---

## 11. Execution Manual (CLI & Python API)

### 11.1 Run Section 1 with Default Case Study Configured in `ecosystem_config.py`
```bash
python -m section1_data_gathering.run_section1
```

### 11.2 Run Section 1 Overriding the Case Study AOI via Python API
You can pass **any** project-relative Shapefile, GeoJSON, or Bounding Box tuple directly to `run_section1()`:

```python
from config.ecosystem_config import DATA_INPUT_DIR
from section1_data_gathering.run_section1 import run_section1

# Option A: Run using a Case Study Shapefile (.shp)
run_section1(aoi_override=DATA_INPUT_DIR / "rfx_aoi_boundary.shp")

# Option B: Run using a Case Study GeoJSON (.geojson)
run_section1(aoi_override=DATA_INPUT_DIR / "rfx_aoi_boundary.geojson")

# Option C: Run using any arbitrary WGS84 Bounding Box (west, south, east, north)
run_section1(aoi_override=(51.322392, 35.747861, 51.331662, 35.752014))
```

### 11.3 Querying the Saved Footprints Directly from PostGIS
```python
from sqlalchemy import create_engine
import geopandas as gpd

engine = create_engine("postgresql+psycopg2://rayflux_admin:RayFlux_2026_Pass@127.0.0.1:5433/rayflux_spatial_db")
gdf = gpd.read_postgis(
    "SELECT building_id, gross_area_m2, building_height_m, num_floors, geometry "
    "FROM public.s01_building_footprints ORDER BY building_id",
    con=engine,
    geom_col="geometry",
)
print(f"Loaded {len(gdf)} 3D buildings from PostGIS (CRS: {gdf.crs})")
```

---

## 12. Engineering Safeguards & Troubleshooting

* **Automatic WFS Token Renewal:** If the WFS server expires its session token mid-download (`HTTP 403 INVALID_VIEWER_SESSION`), `TUM3DFootprintHarvester._get_active_token(force_refresh=True)` automatically negotiates a new token from `/viewer-session` and retries the tile without losing progress.
* **Automatic Esri Zoom Fallback:** If a study area outside a major metropolis does not have Zoom 19 coverage on Esri World Imagery, `detect_best_esri_zoom()` detects the low pixel variance ($\sigma < 8.0$) of the gray `"Map data not yet available"` tile and automatically steps down to Zoom 18 so the output GeoTIFF is always populated with real satellite imagery.
* **Resumable PNG Tile Cache:** All downloaded PNG tiles are stored in `database/cache/s01_tiles/`. If a network drop interrupts a large download, re-running `run_section1.py` resumes instantly from cached tiles on disk.
* **Automatic PostGIS Server Recovery:** If Windows restarts and stops the background PostgreSQL process on port `5433`, `CentralDatabaseManager.get_postgis_engine()` automatically invokes `ensure_postgis_cluster_running()` (`pg_ctl start`) to bring the database online before reading or writing.
