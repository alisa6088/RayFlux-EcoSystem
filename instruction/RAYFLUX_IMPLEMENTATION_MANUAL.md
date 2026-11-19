# RayFlux™ Core Solar Intelligence Ecosystem
## Comprehensive Technical Specification, Standardized Naming Convention, Database Architecture & Implementation Manual

> **Scope of this Document:**  
> This manual is the complete, self-contained engineering specification for implementing the **RayFlux Core Geospatial & AI Ecosystem** (strictly excluding any web/frontend components). All legacy study-area names and ad-hoc filenames have been replaced with a strict, region-agnostic **Enterprise Naming Standard (`rfx_*`)**. It covers:
> 1. **System Architecture & Parallel Execution Flow**
> 2. **Standardized Naming Convention & File Taxonomy** (Shapefiles, GeoPackage, GeoTIFF Rasters, PNGs, Maps, Excel/CSV Tables & Directories)
> 3. **Central Geospatial Database Architecture, Necessities & Schemas**
> 4. **Section 1: Data Gathering & Preprocessing Engine** (High-Res PNG-to-GeoTIFF Imagery, Building Footprints & 3D Synthetic DSM)
> 5. **Section 2: Rooftop Object Detection Engine** (Multi-Modal CV, Shadow Disambiguation, Zero-Shift Policy & Boolean Subtraction)
> 6. **Section 3: Main Solar & Energy Engine** (3D Horizon Ray-Tracing, Solar Irradiance Integration, Empirical Zonal Statistics, PV Yield & Getis-Ord $G_i^*$ Spatial Hotspots)

---

## Table of Contents

1. [Ecosystem Architecture & Parallel Execution Flow](#1-ecosystem-architecture--parallel-execution-flow)
2. [Enterprise Naming Convention & File Taxonomy](#2-enterprise-naming-convention--file-taxonomy)
3. [Complete Directory Structure & Path Addresses](#3-complete-directory-structure--path-addresses)
4. [Central Geospatial Database Necessities, Architecture & Schemas](#4-central-geospatial-database-necessities-architecture--schemas)
5. [Core Engineering Contracts & Bug-Prevention Rules](#5-core-engineering-contracts--bug-prevention-rules)
6. [Environment, Libraries & System Requirements](#6-environment-libraries--system-requirements)
7. [Section 1: Data Gathering & Preprocessing Engine (Calculations & Code)](#7-section-1-data-gathering--preprocessing-engine-calculations--code)
8. [Section 2: Rooftop Object Detection Engine (Calculations & Code)](#8-section-2-rooftop-object-detection-engine-calculations--code)
9. [Section 3: Main Solar & Energy Engine (Calculations & Code)](#9-section-3-main-solar--energy-engine-calculations--code)
10. [Parallel Orchestration & CLI Execution Manual](#10-parallel-orchestration--cli-execution-manual)
11. [Master Reference Table of Physical & Algorithmic Parameters](#11-master-reference-table-of-physical--algorithmic-parameters)

---

## 1. Ecosystem Architecture & Parallel Execution Flow

### 1.1 System Process Flowchart

```mermaid
flowchart TD
    %% SECTION 1: DATA GATHERING & PREPROCESSING
    subgraph S1 ["1. Data Gathering & Preprocessing (High-Res Imagery, Building Footprints & Synthetic DSM)"]
        direction TB
        IMG1["High-Resolution Imagery Harvesting<br/>Fetch High-Res Satellite / Aerial PNG Tiles"] --> IMG2["PNG-to-GeoTIFF Georeferencing<br/>Stitch PNG Tiles & Inject Spatial CRS Metadata"]
        IMG2 --> IMG3["High-Resolution GeoTIFF Images (.tif)<br/>rfx_s01_ras_ortho_rgb.tif"]

        FP1["Building Footprint Extraction<br/>Harvest Vector Building Polygons & Geometry"] --> FP2["Footprint Cleaning & Standardization<br/>Topology Validation & Metric CRS Projection"]
        FP2 --> FP3["Building Footprint Shapefiles (.shp)<br/>rfx_s01_vec_building_footprints.shp"]

        DSM1["3D Building Height Extraction<br/>Retrieve 3D Structural Height Attributes"] --> DSM2["Synthetic DSM Rasterization<br/>Clip to AOI & Burn 3D Heights onto Elevation Grid"]
        FP3 -.->|AOI & Footprints| DSM2
        DSM2 --> DSM3["Synthetic DSM Rasters (.tif)<br/>rfx_s01_ras_synthetic_dsm.tif"]
    end

    %% CENTRAL GEOSPATIAL DATABASE
    subgraph DB ["CENTRAL GEOSPATIAL DATABASE (Single Unified Repository: Vector Shapefiles, GeoTIFF Rasters & Tabular Files)"]
        direction LR
        DB_ORTHO["High-Res GeoTIFFs<br/>rfx_s01_ras_ortho_rgb.tif"]
        DB_FP["Building Footprints<br/>rfx_s01_vec_building_footprints.shp"]
        DB_USABLE["Net Usable Roof Area<br/>rfx_s02_vec_usable_rooftops.shp<br/>& rfx_s02_tbl_usable_area_report.xlsx"]
        DB_DSM["Synthetic DSM<br/>rfx_s01_ras_synthetic_dsm.tif"]
        DB_SOLAR["Final Solar Results<br/>rfx_s03_vec_solar_hotspots_final.shp<br/>& rfx_s03_tbl_solar_potential_final.xlsx"]
    end

    %% SECTION 2: OBJECT DETECTION ENGINE
    subgraph S2 ["2. Rooftop Object Detection Engine (Independent & Parallel Working)"]
        direction TB
        P1["Cadastral Footprint Ingestion<br/>Strict Zero-Shift Ground Truth Enforcement"]
        CV["Multi-Modal Computer Vision Engine<br/>Spectral Indices + GLCM Texture + Gabor + Morphology"]
        SH["Physical Shadow Disambiguation<br/>Separate True Physical Obstacles from Cast Shadows"]
        DIFF["Topological Boolean Difference<br/>Subtract Physical Obstacles from Building Footprints"]
        NET["Usable Area Shapefiles & Excel Reports<br/>rfx_s02_vec_usable_rooftops.shp & .xlsx"]
        
        P1 --> CV --> SH --> DIFF --> NET
    end

    %% SECTION 3: MAIN SOLAR & ENERGY ENGINE
    subgraph S3 ["3. Main Solar & Energy Engine (Independent & Parallel Working)"]
        direction TB
        VAL["Validation & Suitability<br/>Geometry Check & Radiation Threshold"]
        RAD["3D Solar Radiation Modeling<br/>Multi-Dir Horizon & Shadow Ray-Tracing"] --> RAD_OUT["Solar Irradiance Rasters (.tif)<br/>rfx_s03_ras_irradiance_annual.tif"]
        
        VAL --> ZONAL["Zonal Statistics & Surface Aggregation<br/>Combine Solar Irradiance with Net Usable Area & Footprints"]
        RAD_OUT --> ZONAL
        ZONAL --> HOT["PV Electricity Yield & Spatial Hotspots<br/>Energy Generation Calculation (MWh) & Getis-Ord Gi* Clustering"]
        HOT --> SOLAR_OUT["All Solar, Radiation & Energy Results<br/>rfx_s03_vec_solar_hotspots_final.shp, .tif & .xlsx"]
    end

    %% SECTION 1 -> DATABASE (SAVE)
    IMG3 ==>|Save GeoTIFFs to DB| DB_ORTHO
    FP3 ==>|Save Footprints to DB| DB_FP
    DSM3 ==>|Save Synthetic DSM to DB| DB_DSM

    %% DATABASE -> SECTION 2 (IMPORT) & SECTION 2 -> DATABASE (SAVE)
    DB_ORTHO -->|Import GeoTIFFs (.tif)| P1
    DB_FP -->|Import Footprints (.shp)| P1
    NET ==>|Save Usable .shp & .xlsx to DB| DB_USABLE

    %% DATABASE -> SECTION 3 (IMPORT) & SECTION 3 -> DATABASE (SAVE)
    DB_FP -->|Import Footprints (.shp)| VAL
    DB_USABLE -->|Import Usable Area (.shp)| ZONAL
    DB_DSM -->|Import Synthetic DSM (.tif)| RAD
    SOLAR_OUT ==>|Save All Solar Results to DB| DB_SOLAR
```

### 1.2 Independent & Parallel Execution Timeline

```text
TIME ────────────────────────────────────────────────────────────────────────────────────────►

[SECTION 1: Data Gathering & Preprocessing]
  ├── Track 1A: Harvest PNG Tiles ──► Stitch & Warp to rfx_s01_ras_ortho_rgb.tif ─────────┐
  ├── Track 1B: Harvest Footprints & Heights ──► rfx_s01_vec_building_footprints.shp ─────┼──► [SAVE TO CENTRAL DB]
  └── Track 1C: Burn 3D Heights onto 0.5m Grid ──► rfx_s01_ras_synthetic_dsm.tif ─────────┘
                                                                                          │
                     ┌────────────────────────────────────────────────────────────────────┘
                     ▼ (Triggered simultaneously once Section 1 commits to DB)
     ┌───────────────┴───────────────────────────────────────────────────────┐
     │                                                                       │
     ▼ [PARALLEL WORKER A]                                                   ▼ [PARALLEL WORKER B]
[SECTION 2: Object Detection Engine]                              [SECTION 3 (Part 1): 3D Solar Radiation]
  • Imports: rfx_s01_ras_ortho_rgb.tif                              • Imports: rfx_s01_ras_synthetic_dsm.tif
           + rfx_s01_vec_building_footprints.shp                             + rfx_s01_vec_building_footprints.shp
  • Runs Direct Multi-Modal CV (Strict Zero-Shift)                  • Computes Solar Geometry (1,248 timesteps)
  • Separates Cast Shadows vs Physical Obstacles                    • Computes 32-Direction Horizon Angles (Numba)
  • Subtracts Obstacles from Unshifted True Ground Footprints        • Integrates Direct + Diffuse Irradiance (13 Rasters)
  • Saves rfx_s02_vec_usable_rooftops.shp & .xlsx                   • Produces rfx_s03_ras_suitability_mask.tif
     │                                                                       │
     └───────────────────────────────────┬───────────────────────────────────┘
                                         ▼ (Synchronization Barrier: Both stored in DB)
                           [SECTION 3 (Part 2): Zonal Fusion & Hotspots]
                             • Imports: rfx_s02_vec_usable_rooftops.shp + Irradiance Rasters
                             • Runs Empirical Zonal Statistics (exact obstacle-free polygons)
                             • Computes Annual & Monthly PV Electricity Yield (Elec_MWh)
                             • Runs Getis-Ord Gi* Spatial Clustering (999 Permutations)
                             • Saves rfx_s03_vec_solar_hotspots_final.shp, .gpkg, .tif & .xlsx to DB
```

---

## 2. Enterprise Naming Convention & File Taxonomy

### 2.1 Naming Grammar
Every file generated, cached, or stored in the ecosystem follows a strict, deterministic naming pattern:

$$\underbrace{\texttt{rfx}}_{\text{System}} \_ \underbrace{\texttt{<sec>}}_{\text{Section}} \_ \underbrace{\texttt{<kind>}}_{\text{Asset Kind}} \_ \underbrace{\texttt{<descriptor>}}_{\text{Semantic Name}}.\underbrace{\texttt{<ext>}}_{\text{Format}}$$

* **System Prefix (`rfx`):** RayFlux Ecosystem namespace.
* **Section Token (`<sec>`):**
  * `db` = Central Geospatial Database Core Infrastructure
  * `s01` = Section 1 (Data Gathering & Preprocessing Engine)
  * `s02` = Section 2 (Rooftop Object Detection Engine)
  * `s03` = Section 3 (Main Solar & Energy Engine)
* **Asset Kind Token (`<kind>`):**
  * `vec` = Vector Spatial Dataset (`.shp`, `.gpkg`)
  * `ras` = Georeferenced Raster Grid (`.tif`)
  * `tbl` = Tabular Engineering Report or Schedule (`.xlsx`, `.csv`)
  * `img` = Raw Tile, Diagnostic Card, or Analytical Map Image (`.png`, `.jpg`)
  * `log` = Metadata Catalog, Telemetry, or Execution Audit (`.json`, `.log`)

---

### 2.2 Complete Input & Output File Registry

| Section | Standardized Filename | GPKG Layer Name | Format | Relative Database Address | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DB Core** | `rfx_db_master_geodatabase.gpkg` | *(All Layers)* | `.gpkg` | `database/core/` | Single-file SQLite spatial database holding all vector layers with full attribute names & R-Tree indices. |
| **DB Core** | `rfx_db_asset_catalog.json` | — | `.json` | `database/core/` | Automated registry of dataset paths, CRS, bounding boxes, feature counts, SHA-256 hashes & timestamps. |
| **DB Core** | `rfx_db_transaction_audit.log` | — | `.log` | `database/core/` | Chronological read/write transaction and validation log. |
| **Section 1** | `rfx_s01_img_tile_z{z}_x{x}_y{y}.png` | — | `.png` | `database/cache/s01_tiles/` | Raw downloaded $256 \times 256$ high-resolution satellite PNG slippy-map tiles. |
| **Section 1** | `rfx_s01_ras_ortho_rgb.tif` | — | `.tif` | `database/rasters/s01_base/` | Stitched, georeferenced, metric-warped 3-band RGB orthomosaic GeoTIFF (`uint8`). |
| **Section 1** | `rfx_s01_ras_synthetic_dsm.tif` | — | `.tif` | `database/rasters/s01_base/` | Building-only 0.5m Digital Surface Elevation Model (`float32`, ground $= 0.0\text{ m}$). |
| **Section 1** | `rfx_s01_vec_building_footprints.shp` | `s01_building_footprints` | `.shp` | `database/shapefiles/s01_base/` | Validated master building polygons ($\ge 100\text{ m}^2$) with immutable `bldg_id` and `height_m`. |
| **Section 1** | `rfx_s01_tbl_building_inventory.xlsx` | — | `.xlsx` / `.csv` | `database/tables/s01_base/` | Baseline tabular inventory of building IDs, gross areas, heights, floors, and metric centroids. |
| **Section 1** | `rfx_s01_img_base_overview_map.png` | — | `.png` | `database/maps/s01_base/` | QA/QC overview map rendering the Synthetic DSM and validated building footprints. |
| **Section 2** | `rfx_s02_vec_usable_rooftops.shp` | `s02_usable_rooftops` | `.shp` | `database/shapefiles/s02_vision/` | **Primary Vision Output:** Nadir-aligned building polygons with physical obstacles carved out as interior holes. |
| **Section 2** | `rfx_s02_vec_physical_obstacles.shp` | `s02_physical_obstacles` | `.shp` | `database/shapefiles/s02_vision/` | Vectorized 3D physical obstacle polygons (`COOLER_AC`, `PENTHOUSE`, `CHIMNEY_VENT`). |
| **Section 2** | `rfx_s02_vec_cast_shadows.shp` | `s02_cast_shadows` | `.shp` | `database/shapefiles/s02_vision/` | Vectorized radiometric cast shadow polygons separated from physical mass. |
| **Section 2** | `rfx_s02_tbl_usable_area_report.xlsx` | — | `.xlsx` / `.csv` | `database/tables/s02_vision/` | **Primary Vision Table:** Per-building gross area, obstacle area, shadow area, net usable area ($\text{m}^2$ & $\%$), and object counts. |
| **Section 2** | `rfx_s02_img_scene_detection_map.png` | — | `.png` | `database/maps/s02_vision/` | Full-scene thematic map showing usable roof surfaces, obstacles, and shadow patches. |
| **Section 2** | `rfx_s02_img_roof_diag_bldg_{id:04d}.png`| — | `.png` | `database/maps/s02_vision/cards/`| 4-panel per-building diagnostic validation card. |
| **Section 3** | `rfx_s03_tbl_solar_geometry.csv` | — | `.csv` | `database/tables/s03_solar/` | Astronomical sun schedule ($1,248\text{ timesteps}$: timestamp, zenith, azimuth, direction bin, clear-sky GHI). |
| **Section 3** | `rfx_s03_ras_horizon_angles_32dir.tif`| — | `.tif` | `database/rasters/s03_solar/` | 32-band horizon obstruction elevation angle raster (`float32`, degrees). |
| **Section 3** | `rfx_s03_ras_sky_view_factor.tif` | — | `.tif` | `database/rasters/s03_solar/` | Single-band Sky View Factor raster ($\text{SVF} \in [0, 1]$). |
| **Section 3** | `rfx_s03_ras_irradiance_annual.tif` | — | `.tif` | `database/rasters/s03_solar/` | Annual cumulative solar irradiance raster ($\text{kWh/m}^2\text{/yr}$). |
| **Section 3** | `rfx_s03_ras_shadow_fraction_annual.tif`| — | `.tif` | `database/rasters/s03_solar/` | Cumulative daytime shadow duration raster. |
| **Section 3** | `rfx_s03_ras_suitability_mask.tif` | — | `.tif` | `database/rasters/s03_solar/` | Suitable solar irradiance raster masked below economic threshold ($< 400\text{ kWh/m}^2\text{/yr} \rightarrow -9999.0$). |
| **Section 3** | `rfx_s03_ras_irradiance_m01.tif` ... `m12.tif`| — | `.tif` | `database/rasters/s03_solar/monthly/` | 12 monthly cumulative solar irradiance rasters (`m01` = Jan ... `m12` = Dec, $\text{kWh/m}^2\text{/mo}$). |
| **Section 3** | `rfx_s03_vec_solar_zonal_stats.shp` | `s03_solar_zonal_stats` | `.shp` | `database/shapefiles/s03_solar/` | Intermediate vector dataset with annual & monthly zonal irradiance statistics per usable roof. |
| **Section 3** | `rfx_s03_vec_solar_hotspots_final.shp`| `s03_solar_hotspots_final`| `.shp` | `database/shapefiles/s03_solar/` | **Final Solar Vector Deliverable:** Usable roofs with $\text{kWp}$, annual/monthly $\text{MWh}$, and Getis-Ord $G_i^*$ cluster tiers. |
| **Section 3** | `rfx_s03_tbl_solar_potential_final.xlsx`| — | `.xlsx` / `.csv` | `database/tables/s03_solar/` | **Final Solar Tabular Deliverable:** Complete bankable engineering spreadsheet of all solar, energy & hotspot metrics. |
| **Section 3** | `rfx_s03_img_irradiance_heatmap.png` | — | `.png` | `database/maps/s03_solar/` | High-resolution thematic heatmap of annual rooftop solar irradiance. |
| **Section 3** | `rfx_s03_img_hotspots_cluster_map.png`| — | `.png` | `database/maps/s03_solar/` | Spatial priority map classifying 99%, 95%, and 90% confidence Hot Spots and Cold Spots. |
| **Section 3** | `rfx_s03_img_energy_distribution.png` | — | `.png` | `database/maps/s03_solar/` | Statistical distribution histogram and monthly PV generation curve. |

---

## 3. Complete Directory Structure & Path Addresses

```text
RayFlux_Ecosystem/
│
├── config/
│   ├── __init__.py
│   ├── ecosystem_config.py                        # Central configuration & standardized path registry
│   └── cv_hyperparameters.yaml                    # Tunable parameters for Section 2 vision models
│
├── database/                                      # CENTRAL GEOSPATIAL DATABASE (Single Unified Repository)
│   ├── core/
│   │   ├── rfx_db_master_geodatabase.gpkg         # Multi-layer SQLite Spatial Geodatabase (ACID + R-Tree)
│   │   ├── rfx_db_asset_catalog.json              # Provenance, CRS, bounds, SHA-256 & timestamp catalog
│   │   └── rfx_db_transaction_audit.log           # Database read/write transaction log
│   │
│   ├── cache/
│   │   └── s01_tiles/                             # Raw PNG tile cache (rfx_s01_img_tile_z{z}_x{x}_y{y}.png)
│   │
│   ├── shapefiles/                                # Standardized ESRI Shapefile Store (.shp, .shx, .dbf, .prj, .cpg)
│   │   ├── s01_base/
│   │   │   └── rfx_s01_vec_building_footprints.shp
│   │   ├── s02_vision/
│   │   │   ├── rfx_s02_vec_usable_rooftops.shp
│   │   │   ├── rfx_s02_vec_physical_obstacles.shp
│   │   │   └── rfx_s02_vec_cast_shadows.shp
│   │   └── s03_solar/
│   │       ├── rfx_s03_vec_solar_zonal_stats.shp
│   │       └── rfx_s03_vec_solar_hotspots_final.shp
│   │
│   ├── rasters/                                   # Standardized Tiled GeoTIFF Raster Store (.tif)
│   │   ├── s01_base/
│   │   │   ├── rfx_s01_ras_ortho_rgb.tif
│   │   │   └── rfx_s01_ras_synthetic_dsm.tif
│   │   └── s03_solar/
│   │       ├── rfx_s03_ras_horizon_angles_32dir.tif
│   │       ├── rfx_s03_ras_sky_view_factor.tif
│   │       ├── rfx_s03_ras_irradiance_annual.tif
│   │       ├── rfx_s03_ras_shadow_fraction_annual.tif
│   │       ├── rfx_s03_ras_suitability_mask.tif
│   │       └── monthly/
│   │           ├── rfx_s03_ras_irradiance_m01.tif
│   │           ├── ...
│   │           └── rfx_s03_ras_irradiance_m12.tif
│   │
│   ├── tables/                                    # Standardized Excel (.xlsx) & CSV (.csv) Store
│   │   ├── s01_base/
│   │   │   ├── rfx_s01_tbl_building_inventory.xlsx
│   │   │   └── rfx_s01_tbl_building_inventory.csv
│   │   ├── s02_vision/
│   │   │   ├── rfx_s02_tbl_usable_area_report.xlsx
│   │   │   └── rfx_s02_tbl_usable_area_report.csv
│   │   └── s03_solar/
│   │       ├── rfx_s03_tbl_solar_geometry.csv
│   │       ├── rfx_s03_tbl_solar_potential_final.xlsx
│   │       └── rfx_s03_tbl_solar_potential_final.csv
│   │
│   └── maps/                                      # Standardized Visual PNG Maps & Diagnostic Cards Store
│       ├── s01_base/
│       │   └── rfx_s01_img_base_overview_map.png
│       ├── s02_vision/
│       │   ├── rfx_s02_img_scene_detection_map.png
│       │   └── cards/
│       │       └── rfx_s02_img_roof_diag_bldg_0001.png
│       └── s03_solar/
│           ├── rfx_s03_img_irradiance_heatmap.png
│           ├── rfx_s03_img_hotspots_cluster_map.png
│           └── rfx_s03_img_energy_distribution.png
│
├── core_db/                                       # Database Engine & Spatial Environment Guards
│   ├── __init__.py
│   ├── env_guard.py
│   └── database_manager.py
│
├── section1_data_gathering/                       # MODULE 1: Independent Data Gathering & Preprocessing
│   ├── __init__.py
│   ├── footprint_harvester.py
│   ├── png_to_geotiff_harvester.py
│   ├── synthetic_dsm_builder.py
│   └── run_section1.py
│
├── section2_object_detection/                     # MODULE 2: Independent Rooftop Object Detection Engine
│   ├── __init__.py
│   ├── footprint_validator.py                     # Zero-Shift Ground Truth Validator & Spatial Bounding
│   ├── vision_models/
│   │   ├── __init__.py
│   │   ├── chromaticity_ndci.py
│   │   ├── texture_glcm.py
│   │   ├── gabor_bank.py
│   │   ├── morphology_tophat.py
│   │   └── shadow_disambiguator.py
│   ├── vectorizer_topology.py
│   └── run_section2.py
│
├── section3_solar_engine/                         # MODULE 3: Independent Main Solar & Energy Engine
│   ├── __init__.py
│   ├── v01_solar_geometry.py
│   ├── v01_horizon_numba.py
│   ├── v01_radiation_integrator.py
│   ├── v02_v03_suitability.py
│   ├── v04_zonal_fusion.py
│   ├── v05_pv_yield_and_hotspots.py
│   └── run_section3.py
│
├── logs/
├── environment.yml
├── requirements.txt
└── run_ecosystem.py                               # Master Parallel Orchestrator
```

---

## 4. Central Geospatial Database Necessities, Architecture & Schemas

### 4.1 Database Necessities & Architectural Requirements
To serve as a reliable backbone for independent, parallel-working engines, the Central Geospatial Database enforces **7 technical necessities**:

1. **Dual Vector Persistence (SQLite GeoPackage + ESRI Shapefile):**
   * Every vector output is simultaneously written to `rfx_db_master_geodatabase.gpkg` (preserving full column names, SQL queryability, and R-Tree spatial indexing) AND `database/shapefiles/` (using deterministic $\le 10$-character column names with a bidirectional dictionary mapping so legacy GIS/CAD software can open `.shp` files without truncation ambiguity).
2. **Cloud-Optimized / Tiled Raster Storage (`256x256` Blocks + LZW Compression):**
   * All `.tif` rasters are written with `tiled=True`, `blockxsize=256`, `blockysize=256`, `compress='lzw'`, and `predictor=2` (horizontal differencing for floating-point grids). This allows Section 2 and Section 3 to stream $256 \times 256$ windows directly from disk without loading multi-gigabyte rasters into memory.
3. **Strict Coordinate Reference System Lock (`target_crs`):**
   * The Database Manager rejects or automatically reprojects any incoming vector or raster whose CRS does not match the project's metric UTM CRS (e.g., `EPSG:32639`). Web Mercator (`EPSG:3857`) and geographic (`EPSG:4326`) coordinates are converted in Section 1 prior to database commit.
4. **Immutable Primary Key Integrity (`building_id` / `bldg_id`):**
   * `building_id` ($1, 2, \dots, N$) is generated deterministically once in Section 1 (sorted North-to-South, West-to-East). Section 2 and Section 3 preserve `building_id` as an immutable foreign/primary key, enabling exact 1-to-1 relational joins across all vector layers and Excel tables.
5. **Atomic Write-Then-Rename Transactions:**
   * Because Section 2 and Section 3 run in parallel, files are written to temporary `.tmp` paths and atomically renamed upon completion (`os.replace`), preventing partial-read race conditions.
6. **Automated Provenance & Checksum Catalog (`rfx_db_asset_catalog.json`):**
   * Every database write updates `rfx_db_asset_catalog.json` with the dataset's exact path, CRS, bounding box, pixel resolution or feature count, SHA-256 hash, and ISO-8601 timestamp.
7. **Dual Tabular Export (`.xlsx` + `.csv`):**
   * Every statistical report is saved both as a formatted Microsoft Excel workbook (`.xlsx` via `openpyxl`) for engineering/financial review and a UTF-8 `.csv` for automated data pipelines.

---

### 4.2 Complete Database Table & Layer Schemas

#### Schema A: `s01_building_footprints` (`rfx_s01_vec_building_footprints.shp` & `rfx_s01_tbl_building_inventory.xlsx`)
| Shapefile Field ($\le 10$ chars) | GPKG / Excel Full Column | Data Type | Units | Description |
| :--- | :--- | :--- | :--- | :--- |
| `bldg_id` | `building_id` | `int64` | — | **Primary Key ($1 \dots N$)**. Immutable across the entire ecosystem. |
| `src_id` | `source_feature_id` | `str` | — | Original external catalog feature identifier. |
| `gross_area` | `gross_area_m2` | `float64` | $\text{m}^2$ | Validated gross 2D footprint area (`>= 100.0`). |
| `height_m` | `building_height_m` | `float64` | $\text{m}$ | 3D structural roof height above ground (`default = 9.6`). |
| `floors` | `num_floors` | `int32` | count | Estimated story count ($\max(1, \text{round}(\text{height\_m} / 3.2))$). |
| `cx_utm` | `centroid_x_utm` | `float64` | $\text{m}$ | Footprint centroid Easting in metric UTM CRS. |
| `cy_utm` | `centroid_y_utm` | `float64` | $\text{m}$ | Footprint centroid Northing in metric UTM CRS. |
| `geometry` | `geometry` | `Polygon` | $\text{m}$ | Topologically valid exterior building footprint polygon. |

#### Schema B: `s02_usable_rooftops` (`rfx_s02_vec_usable_rooftops.shp` & `rfx_s02_tbl_usable_area_report.xlsx`)
| Shapefile Field ($\le 10$ chars) | GPKG / Excel Full Column | Data Type | Units | Description |
| :--- | :--- | :--- | :--- | :--- |
| `bldg_id` | `building_id` | `int64` | — | **Primary/Foreign Key** matching `s01_building_footprints.building_id`. |
| `gross_area` | `gross_area_m2` | `float64` | $\text{m}^2$ | Gross footprint area prior to obstacle subtraction. |
| `obj_area` | `obstacle_area_m2` | `float64` | $\text{m}^2$ | Total area of true 3D physical obstacles subtracted from the roof. |
| `shd_area` | `cast_shadow_area_m2` | `float64` | $\text{m}^2$ | Total area of disambiguated cast shadows (retained as installable surface). |
| `usable_are` | `usable_area_m2` | `float64` | $\text{m}^2$ | **True Net Usable Area** ($\text{Geometry.area}$ of obstacle-carved roof). |
| `usable_pct` | `usable_area_pct` | `float64` | $\%$ | Empirical usable percentage ($(\text{usable\_area\_m2} / \text{gross\_area\_m2}) \times 100$). |
| `obj_cnt` | `obstacle_count` | `int32` | count | Total number of physical obstacles detected on the roof. |
| `cooler_cnt`| `cooler_ac_count` | `int32` | count | Count of detected evaporative coolers / HVAC units (`COOLER_AC`). |
| `penth_cnt` | `penthouse_count` | `int32` | count | Count of detected elevator/stairwell bulkheads (`PENTHOUSE`). |
| `vent_cnt` | `chimney_vent_count` | `int32` | count | Count of detected chimney flues / vents (`CHIMNEY_VENT`). |
| `dx_shift` | `parallax_dx_m` | `float64` | $\text{m}$ | Easting shift locked to 0.0 (Zero-Shift Ground Truth Policy). |
| `dy_shift` | `parallax_dy_m` | `float64` | $\text{m}$ | Northing shift locked to 0.0 (Zero-Shift Ground Truth Policy). |
| `roof_stat` | `suitability_status` | `str` | — | Categorical rating (`EXCELLENT`, `GOOD`, `MODERATE`, `LIMITED`). |
| `geometry` | `geometry` | `Polygon` / `MultiPolygon` | $\text{m}$ | **Nadir-aligned polygon with interior obstacle holes carved out.** |

#### Schema C: `s03_solar_hotspots_final` (`rfx_s03_vec_solar_hotspots_final.shp` & `rfx_s03_tbl_solar_potential_final.xlsx`)
| Shapefile Field ($\le 10$ chars) | GPKG / Excel Full Column | Data Type | Units | Description |
| :--- | :--- | :--- | :--- | :--- |
| `bldg_id` | `building_id` | `int64` | — | **Primary/Foreign Key** matching Schema A & Schema B. |
| `height_m` | `building_height_m` | `float64` | $\text{m}$ | Building structural height from Schema A. |
| `gross_area` | `gross_area_m2` | `float64` | $\text{m}^2$ | Gross footprint area from Schema A. |
| `usable_are` | `usable_area_m2` | `float64` | $\text{m}^2$ | True obstacle-free net usable area from Schema B. |
| `usable_pct` | `usable_area_pct` | `float64` | $\%$ | Empirical usable roof percentage from Schema B. |
| `rad_count` | `suitable_pixel_count` | `int32` | pixels | Count of suitable irradiance pixels ($\ge 400\text{ kWh/m}^2\text{/yr}$) inside net roof. |
| `mean_kwh` | `mean_kwh_m2_yr` | `float64` | $\text{kWh/m}^2\text{/yr}$ | Mean annual solar irradiance on the net usable area. |
| `min_kwh` | `min_kwh_m2_yr` | `float64` | $\text{kWh/m}^2\text{/yr}$ | Minimum annual solar irradiance on the net usable area. |
| `max_kwh` | `max_kwh_m2_yr` | `float64` | $\text{kWh/m}^2\text{/yr}$ | Maximum annual solar irradiance on the net usable area. |
| `std_kwh` | `std_kwh_m2_yr` | `float64` | $\text{kWh/m}^2\text{/yr}$ | Standard deviation of irradiance across the roof (shading variability). |
| `kwh_m01` ... `kwh_m12` | `mean_kwh_m2_m01` ... `mean_kwh_m2_m12` | `float64` | $\text{kWh/m}^2\text{/mo}$ | 12 monthly mean solar irradiance columns (`m01` = Jan ... `m12` = Dec). |
| `inc_mwh_yr`| `incident_solar_mwh_yr`| `float64` | $\text{MWh/yr}$ | Total annual incident solar energy ($\text{mean\_kwh} \times \text{usable\_are} / 1000$). |
| `cap_kwp` | `installed_capacity_kwp`| `float64` | $\text{kWp}$ | Installable DC peak PV capacity ($\text{usable\_are} \times \eta_{\text{PV}}$). |
| `elec_mwh` | `elec_yield_mwh_yr` | `float64` | $\text{MWh/yr}$ | **Net Annual PV Electricity Yield** ($\eta_{\text{PV}} \times PR \times \text{inc\_mwh\_yr}$). |
| `el_mwh_01` ... `el_mwh_12`| `elec_mwh_m01` ... `elec_mwh_m12` | `float64` | $\text{MWh/mo}$ | 12 monthly net PV electricity yield columns (`m01` = Jan ... `m12` = Dec). |
| `gi_stat` | `gi_star_statistic` | `float64` | — | Local Getis-Ord $G_i^*$ spatial clustering statistic. |
| `gi_zscore` | `gi_z_score` | `float64` | $\sigma$ | Standardized Getis-Ord $G_i^*$ Z-score. |
| `gi_pvalue` | `gi_p_value` | `float64` | — | Pseudo $p$-value from 999 Monte Carlo permutations. |
| `gi_class` | `gi_cluster_class` | `str` | — | Priority tier (`Hot Spot - 99% Confidence`, `95%`, `90%`, `Cold Spot`, `Not Significant`). |
| `geometry` | `geometry` | `Polygon` / `MultiPolygon` | $\text{m}$ | Net obstacle-free building polygon in metric UTM CRS. |

---

## 5. Core Engineering Contracts & Bug-Prevention Rules

1. **Contract 1 — Unified Metric Coordinate Reference System:**
   All PNG tiles (`EPSG:3857`) and global vectors (`EPSG:4326`) are reprojected/warped to the target metric UTM CRS in Section 1 before database commit.
2. **Contract 2 — Reconciled Footprint Geometry & Immutable `building_id`:**
   Section 1 merges footprint polygons and 3D height attributes into one unified dataset (`rfx_s01_vec_building_footprints.shp`), filters $\text{gross\_area\_m2} \ge 100.0\text{ m}^2$, and assigns an immutable `building_id` ($1 \dots N$).
3. **Contract 3 — STRICT PROHIBITION OF SHAPEFILE / FOOTPRINT SHIFTING (Zero-Shift Ground Truth Policy):**
   > [!IMPORTANT]
   > **NO SHAPEFILE SHIFTING PERMITTED:** Under no circumstances should building footprints or vector shapefiles be translated, shifted, or offset (`dx = 0.0`, `dy = 0.0`).
   > 
   > **Why Shifting is Strictly Prohibited:**
   > - **Cadastral & Ground Truth Integrity:** Cadastral footprints represent true legal property boundaries and georeferenced ground foundations. Applying artificial 2D offsets distorts real-world geometry and creates severe boundary conflicts with adjacent parcels, streets, and infrastructure.
   > - **Non-Linear Physical Variation:** Parallax/relief displacement is inherently non-linear across any urban scene—it depends dynamically on individual building heights ($h$), localized topography, and radial distance from the satellite nadir track. Applying an arbitrary or constant $(dx, dy)$ translation across a shapefile is photogrammetrically flawed and introduces massive positional errors.
   > - **Elevation Grid Synchronization:** Section 3 generates 3D Synthetic DSM elevation rasters (`rfx_s01_ras_synthetic_dsm.tif`) anchored strictly to ground nadir footprints. Any shift in Section 2 instantly desynchronizes the rooftop obstacle masks from the 3D ray-tracing horizon calculations.
   > 
   > Therefore, all rooftop object detection and spatial processing must strictly operate on the **original, unshifted georeferenced footprint** (`\Delta x = 0.0\text{ m}, \Delta y = 0.0\text{ m}`). No parallax offset or vector translation is allowed.
4. **Contract 4 — True Parallelism Between Section 2 and Section 3 (`Phase v01`):**
   Section 2 (Object Detection) and Section 3's 3D Solar Radiation modeling (`Phase v01–v03`) run concurrently in parallel right after Section 1 finishes. Section 3 only reads `rfx_s02_vec_usable_rooftops.shp` at `Phase v04` (Zonal Statistics).

---

## 6. Environment, Libraries & System Requirements

### 6.1 Conda Environment (`environment.yml`)
```yaml
name: rayflux-ecosystem
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.10
  - gdal>=3.7.0
  - proj>=9.2.0
  - geos>=3.12.0
  - rasterio>=1.3.8
  - geopandas>=0.14.0
  - shapely>=2.0.2
  - pyproj>=3.6.1
  - fiona>=1.9.5
  - pyarrow>=14.0.0
  - numpy>=1.24.0,<2.0.0
  - scipy>=1.11.0
  - pandas>=2.1.0
  - numba>=0.58.0
  - scikit-image>=0.22.0
  - scikit-learn>=1.3.0
  - opencv>=4.8.0
  - matplotlib>=3.8.0
  - openpyxl>=3.1.2
  - pip
  - pip:
      - overturemaps>=0.7.0
      - mercantile>=1.2.1
      - contextily>=1.4.0
      - pvlib>=0.10.2
      - rasterstats>=0.19.0
      - libpysal>=4.9.2
      - esda>=2.5.1
      - pyyaml>=6.0.1
      - requests>=2.31.0
      - urllib3>=2.0.0
      - pillow>=10.1.0
      - tqdm>=4.66.0
```

### 6.2 PROJ/GDAL Stabilizer (`core_db/env_guard.py`)
```python
"""
core_db/env_guard.py
Isolates Python's internal PROJ/GDAL database from conflicting system variables.
"""
import os
import warnings
import pyproj

def initialize_spatial_env() -> str:
    os.environ.pop("PROJ_LIB", None)
    os.environ.pop("PROJ_DATA", None)
    proj_data_dir = pyproj.datadir.get_data_dir()
    os.environ["PROJ_LIB"] = proj_data_dir
    os.environ["PROJ_DATA"] = proj_data_dir
    os.environ["GDAL_PAM_ENABLED"] = "NO"
    warnings.filterwarnings("ignore", category=UserWarning)
    return proj_data_dir
```

### 6.3 Master Configuration & Standardized Path Registry (`config/ecosystem_config.py`)
```python
"""
config/ecosystem_config.py
Central configuration and standardized rfx_* file path registry.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_ROOT = PROJECT_ROOT / "database"


@dataclass
class DatabasePaths:
    # Core Database Infrastructure
    master_gpkg: Path = DB_ROOT / "core" / "rfx_db_master_geodatabase.gpkg"
    catalog_json: Path = DB_ROOT / "core" / "rfx_db_asset_catalog.json"
    audit_log: Path = DB_ROOT / "core" / "rfx_db_transaction_audit.log"

    # Section 1: Base Data & Preprocessing Store
    tile_cache_dir: Path = DB_ROOT / "cache" / "s01_tiles"
    s01_ortho_tif: Path = DB_ROOT / "rasters" / "s01_base" / "rfx_s01_ras_ortho_rgb.tif"
    s01_synthetic_dsm_tif: Path = DB_ROOT / "rasters" / "s01_base" / "rfx_s01_ras_synthetic_dsm.tif"
    s01_footprints_shp: Path = DB_ROOT / "shapefiles" / "s01_base" / "rfx_s01_vec_building_footprints.shp"
    s01_inventory_xlsx: Path = DB_ROOT / "tables" / "s01_base" / "rfx_s01_tbl_building_inventory.xlsx"
    s01_overview_map_png: Path = DB_ROOT / "maps" / "s01_base" / "rfx_s01_img_base_overview_map.png"

    # Section 2: Rooftop Object Detection Store
    s02_usable_rooftops_shp: Path = DB_ROOT / "shapefiles" / "s02_vision" / "rfx_s02_vec_usable_rooftops.shp"
    s02_obstacles_shp: Path = DB_ROOT / "shapefiles" / "s02_vision" / "rfx_s02_vec_physical_obstacles.shp"
    s02_shadows_shp: Path = DB_ROOT / "shapefiles" / "s02_vision" / "rfx_s02_vec_cast_shadows.shp"
    s02_usable_report_xlsx: Path = DB_ROOT / "tables" / "s02_vision" / "rfx_s02_tbl_usable_area_report.xlsx"
    s02_scene_map_png: Path = DB_ROOT / "maps" / "s02_vision" / "rfx_s02_img_scene_detection_map.png"
    s02_cards_dir: Path = DB_ROOT / "maps" / "s02_vision" / "cards"

    # Section 3: Main Solar & Energy Store
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
        return self.s03_monthly_rad_dir / f"rfx_s03_ras_irradiance_m{month_idx:02d}.tif"

    def ensure_directories(self) -> None:
        for val in self.__dict__.values():
            if isinstance(val, Path):
                d = val if val.suffix == "" else val.parent
                d.mkdir(parents=True, exist_ok=True)


@dataclass
class EcosystemConfig:
    # Target Area of Interest Bounding Box (West, South, East, North in EPSG:4326)
    aoi_bbox_wgs84: Tuple[float, float, float, float] = (51.322392, 35.747861, 51.331662, 35.752014)
    target_crs: str = "EPSG:32639"
    min_building_area_m2: float = 100.0
    default_building_height_m: float = 9.6

    # Section 1 Parameters
    imagery_zoom: int = 19
    imagery_provider: str = "google"
    dsm_resolution_m: float = 0.50

    # Section 2 Parameters
    min_obstacle_area_m2: float = 0.20
    min_usable_patch_m2: float = 2.00

    # Section 3 Parameters
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

    db: DatabasePaths = field(default_factory=DatabasePaths)
```

### 6.4 Central Database Manager (`core_db/database_manager.py`)
```python
"""
core_db/database_manager.py
Atomic Database Manager handling dual GPKG + Shapefile persistence, GeoTIFF registration,
Excel/CSV generation, SHA-256 cataloging, and transaction audit logging.
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

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig

# Standardized bidirectional mapping between full GPKG/Excel columns and <=10-char Shapefile columns
SHP_COLUMN_MAP: Dict[str, str] = {
    "building_id": "bldg_id",
    "source_feature_id": "src_id",
    "gross_area_m2": "gross_area",
    "building_height_m": "height_m",
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
    "suitable_pixel_count": "rad_count",
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
    def __init__(self, config: EcosystemConfig):
        self.config = config
        self.db = config.db
        self.db.ensure_directories()

    def _log_audit(self, action: str, target: str, details: str) -> None:
        ts = datetime.now().isoformat()
        line = f"[{ts}] [{action}] {target} | {details}\n"
        with open(self.db.audit_log, "a", encoding="utf-8") as f:
            f.write(line)

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
        if gdf.crs is None or gdf.crs.to_string() != self.config.target_crs:
            gdf = gdf.to_crs(self.config.target_crs)

        if "building_id" in gdf.columns:
            gdf = gdf.sort_values("building_id").reset_index(drop=True)

        # 1. Commit full-schema layer to Master GeoPackage
        gdf.to_file(self.db.master_gpkg, layer=gpkg_layer, driver="GPKG")

        # 2. Commit <=10-char schema to Standardized ESRI Shapefile
        gdf_shp = gdf.rename(columns=SHP_COLUMN_MAP)
        shp_path.parent.mkdir(parents=True, exist_ok=True)
        gdf_shp.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

        # 3. Commit Tabular Excel (.xlsx) & CSV (.csv)
        if excel_path is not None:
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            df_tab = pd.DataFrame(gdf.drop(columns=["geometry"], errors="ignore"))
            df_tab.to_excel(excel_path, index=False, engine="openpyxl")
            df_tab.to_csv(excel_path.with_suffix(".csv"), index=False, encoding="utf-8")

        self._update_catalog(
            gpkg_layer,
            {
                "kind": "vector",
                "shapefile": str(shp_path),
                "gpkg_layer": gpkg_layer,
                "excel": str(excel_path) if excel_path else None,
                "feature_count": len(gdf),
                "crs": str(gdf.crs),
                "bounds": [float(b) for b in gdf.total_bounds],
                "sha256": self._file_sha256(shp_path),
            },
        )
        self._log_audit("WRITE_VECTOR", gpkg_layer, f"count={len(gdf)} crs={gdf.crs}")

    def load_vector_dataset(self, shp_path: Path, gpkg_layer: Optional[str] = None) -> gpd.GeoDataFrame:
        if gpkg_layer and self.db.master_gpkg.exists():
            try:
                gdf = gpd.read_file(self.db.master_gpkg, layer=gpkg_layer)
            except Exception:
                gdf = gpd.read_file(shp_path)
        else:
            gdf = gpd.read_file(shp_path)

        gdf = gdf.rename(columns=INV_SHP_COLUMN_MAP)
        if gdf.crs is not None and gdf.crs.to_string() != self.config.target_crs:
            gdf = gdf.to_crs(self.config.target_crs)
        self._log_audit("READ_VECTOR", gpkg_layer or shp_path.name, f"count={len(gdf)}")
        return gdf

    def register_raster(self, raster_path: Path, key: str) -> None:
        with rasterio.open(raster_path) as src:
            self._update_catalog(
                key,
                {
                    "kind": "raster",
                    "path": str(raster_path),
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
```

---

## 7. Section 1: Data Gathering & Preprocessing Engine (Calculations & Code)

### 7.1 Mathematical Formulations
1. **Slippy-Map PNG Tile Indexing & Metric GeoTIFF Warping:**
   Given AOI $(\lambda_{\min}, \phi_{\min}, \lambda_{\max}, \phi_{\max})$ and zoom $z$:
   $$x_{\text{tile}}(\lambda) = \left\lfloor \frac{\lambda + 180^\circ}{360^\circ} \cdot 2^z \right\rfloor, \qquad y_{\text{tile}}(\phi) = \left\lfloor \left(1 - \frac{\ln(\tan(\phi) + \sec(\phi))}{\pi}\right) \cdot 2^{z-1} \right\rfloor$$
   Tiles are cached as `rfx_s01_img_tile_z{z}_x{x}_y{y}.png`, stitched into a canvas of size $W_{3857} \times H_{3857}$, georeferenced in `EPSG:3857`, and warped via bilinear resampling to `target_crs` (`rfx_s01_ras_ortho_rgb.tif`).
2. **Building Footprint & 3D Height Reconciliation:**
   Extracts building polygons, joins 3D LoD1 height attributes, repairs topology (`make_valid`), filters $\text{gross\_area\_m2} \ge 100.0\text{ m}^2$, sorts North-West to South-East, and assigns `building_id` $= 1 \dots N$ (`rfx_s01_vec_building_footprints.shp`).
3. **Synthetic DSM Rasterization:**
   Burns `building_height_m` onto a $0.50\text{ m}$ metric grid with ground elevation $0.0\text{ m}$ (`rfx_s01_ras_synthetic_dsm.tif`).

### 7.2 Section 1 Implementation (`section1_data_gathering/run_section1.py`)
```python
"""
section1_data_gathering/run_section1.py
Populates Central Database with:
  - rfx_s01_vec_building_footprints.shp & rfx_s01_tbl_building_inventory.xlsx
  - rfx_s01_ras_synthetic_dsm.tif
  - rfx_s01_ras_ortho_rgb.tif (from cached rfx_s01_img_tile_z*_x*_y*.png)
"""
from io import BytesIO
import math
from pathlib import Path
import time
import geopandas as gpd
import mercantile
import numpy as np
import overturemaps
import pandas as pd
from PIL import Image
from pyarrow import fs
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import calculate_default_transform, reproject, Resampling
import requests
from shapely.geometry import box
from shapely.validation import make_valid

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig
from core_db.database_manager import CentralDatabaseManager

Image.MAX_IMAGE_PIXELS = None


def harvest_and_clean_footprints(
    config: EcosystemConfig,
    external_3d_heights_shp: str | None = None,
) -> gpd.GeoDataFrame:
    west, south, east, north = config.aoi_bbox_wgs84
    bbox_utm = gpd.GeoDataFrame(geometry=[box(west, south, east, north)], crs="EPSG:4326").to_crs(config.target_crs)
    xmin, ymin, xmax, ymax = bbox_utm.total_bounds

    s3 = fs.S3FileSystem(region="us-west-2", anonymous=True)
    infos = s3.get_file_info(fs.FileSelector("overturemaps-us-west-2/release", recursive=False))
    releases = sorted([f.base_name for f in infos if f.base_name.startswith("202")])
    latest_release = releases[-1]

    gdf = overturemaps.core.geodataframe("building", bbox=(west, south, east, north), release=latest_release)
    gdf = gdf[gdf.geometry.notnull()].copy()
    gdf.set_crs(epsg=4326, inplace=True, allow_override=True)
    gdf = gdf.to_crs(config.target_crs)

    if external_3d_heights_shp and Path(external_3d_heights_shp).exists():
        h_gdf = gpd.read_file(external_3d_heights_shp, bbox=(xmin, ymin, xmax, ymax))
        if h_gdf.crs != config.target_crs:
            h_gdf = h_gdf.to_crs(config.target_crs)
        if "height" in h_gdf.columns and len(h_gdf) > 0:
            joined = gpd.sjoin_nearest(gdf, h_gdf[["height", "geometry"]], how="left", max_distance=10.0, rsuffix="ext")
            joined = joined[~joined.index.duplicated(keep="first")]
            if "height_ext" in joined.columns:
                gdf["height"] = joined["height_ext"].combine_first(
                    gdf["height"] if "height" in gdf.columns else pd.Series(index=gdf.index, dtype=float)
                )

    gdf["geometry"] = gdf.geometry.apply(lambda g: make_valid(g).buffer(0))
    gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    gdf["gross_area_m2"] = gdf.geometry.area.round(2)
    gdf = gdf[gdf["gross_area_m2"] >= config.min_building_area_m2].copy()

    if "height" not in gdf.columns:
        gdf["height"] = config.default_building_height_m
    gdf["building_height_m"] = pd.to_numeric(gdf["height"], errors="coerce").fillna(config.default_building_height_m).round(2)
    gdf["num_floors"] = np.maximum(1, np.round(gdf["building_height_m"] / 3.2)).astype(int)
    gdf["centroid_x_utm"] = gdf.geometry.centroid.x.round(2)
    gdf["centroid_y_utm"] = gdf.geometry.centroid.y.round(2)
    gdf["source_feature_id"] = gdf["id"].astype(str) if "id" in gdf.columns else [f"src_{i}" for i in range(len(gdf))]

    gdf = gdf.sort_values(by=["centroid_y_utm", "centroid_x_utm"], ascending=[False, True]).reset_index(drop=True)
    gdf["building_id"] = np.arange(1, len(gdf) + 1, dtype=np.int64)

    return gdf[[
        "building_id", "source_feature_id", "gross_area_m2",
        "building_height_m", "num_floors", "centroid_x_utm", "centroid_y_utm", "geometry"
    ]]


def generate_synthetic_dsm(config: EcosystemConfig, footprints_gdf: gpd.GeoDataFrame) -> Path:
    west, south, east, north = config.aoi_bbox_wgs84
    bbox_utm = gpd.GeoDataFrame(geometry=[box(west, south, east, north)], crs="EPSG:4326").to_crs(config.target_crs)
    xmin, ymin, xmax, ymax = bbox_utm.total_bounds

    res = config.dsm_resolution_m
    width = int(math.ceil((xmax - xmin) / res))
    height_dim = int(math.ceil((ymax - ymin) / res))
    transform = from_origin(xmin, ymax, res, res)

    shapes = ((geom, float(h)) for geom, h in zip(footprints_gdf.geometry, footprints_gdf["building_height_m"]))
    dsm_array = rasterize(
        shapes=shapes,
        out_shape=(height_dim, width),
        transform=transform,
        fill=0.0,
        dtype="float32",
    )

    out_path = config.db.s01_synthetic_dsm_tif
    with rasterio.open(
        out_path, "w",
        driver="GTiff",
        height=height_dim,
        width=width,
        count=1,
        dtype="float32",
        crs=config.target_crs,
        transform=transform,
        compress="lzw",
        predictor=2,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        nodata=-9999.0,
    ) as dst:
        dst.write(dsm_array, 1)

    return out_path


def harvest_png_tiles_to_metric_geotiff(config: EcosystemConfig) -> Path:
    west, south, east, north = config.aoi_bbox_wgs84
    zoom = config.imagery_zoom
    tiles = list(mercantile.tiles(west, south, east, north, zoom))

    xs, ys = [t.x for t in tiles], [t.y for t in tiles]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    cols, rows = (max_x - min_x) + 1, (max_y - min_y) + 1
    tile_size = 256
    total_w, total_h = cols * tile_size, rows * tile_size

    canvas = np.zeros((total_h, total_w, 3), dtype=np.uint8)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.google.com/maps/" if config.imagery_provider == "google" else "https://www.arcgis.com/",
    }
    url_tpl = (
        "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
        if config.imagery_provider == "google"
        else "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    )

    for tile in tiles:
        cached_png = config.db.tile_cache_dir / f"rfx_s01_img_tile_z{tile.z}_x{tile.x}_y{tile.y}.png"
        if cached_png.exists():
            tile_img = Image.open(cached_png).convert("RGB")
        else:
            url = url_tpl.format(x=tile.x, y=tile.y, z=tile.z)
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                continue
            tile_img = Image.open(BytesIO(res.content)).convert("RGB")
            tile_img.save(cached_png, format="PNG")

        px_x = (tile.x - min_x) * tile_size
        px_y = (tile.y - min_y) * tile_size
        canvas[px_y : px_y + tile_size, px_x : px_x + tile_size] = np.array(tile_img)

    ul_bounds = mercantile.xy_bounds(min_x, min_y, zoom)
    lr_bounds = mercantile.xy_bounds(max_x, max_y, zoom)
    src_transform = from_bounds(ul_bounds.left, lr_bounds.bottom, lr_bounds.right, ul_bounds.top, total_w, total_h)
    src_crs = "EPSG:3857"

    dst_transform, dst_w, dst_h = calculate_default_transform(
        src_crs, config.target_crs, total_w, total_h,
        left=ul_bounds.left, bottom=lr_bounds.bottom, right=lr_bounds.right, top=ul_bounds.top
    )

    out_path = config.db.s01_ortho_tif
    with rasterio.open(
        out_path, "w",
        driver="GTiff",
        height=dst_h,
        width=dst_w,
        count=3,
        dtype="uint8",
        crs=config.target_crs,
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
                dst_crs=config.target_crs,
                resampling=Resampling.bilinear,
            )
            dst.write(dst_band, b + 1)

    return out_path


def run_section1(external_3d_heights_shp: str | None = None) -> None:
    t0 = time.time()
    config = EcosystemConfig()
    db_mgr = CentralDatabaseManager(config)

    footprints_gdf = harvest_and_clean_footprints(config, external_3d_heights_shp=external_3d_heights_shp)
    db_mgr.save_vector_dataset(
        footprints_gdf,
        shp_path=config.db.s01_footprints_shp,
        gpkg_layer="s01_building_footprints",
        excel_path=config.db.s01_inventory_xlsx,
    )

    dsm_path = generate_synthetic_dsm(config, footprints_gdf)
    db_mgr.register_raster(dsm_path, "s01_synthetic_dsm")

    ortho_path = harvest_png_tiles_to_metric_geotiff(config)
    db_mgr.register_raster(ortho_path, "s01_ortho_rgb")

    print(f"[Section 1] Completed in {time.time() - t0:.2f}s.")
```

---

## 8. Section 2: Rooftop Object Detection Engine (Calculations & Code)

### 8.1 Mathematical Formulations
1. **Strict Zero-Shift Policy (No Parallax Displacement / No Shapefile Shifting):**
   > [!IMPORTANT]
   > Building footprint shapefiles and extracted obstacle geometries MUST NOT be shifted or offset ($\Delta x = 0.0\text{ m}, \Delta y = 0.0\text{ m}$).
   > $$\mathcal{P}_i^{\text{img}} \equiv \mathcal{P}_i^{\text{nadir}} \quad (\Delta x_i = 0.0, \, \Delta y_i = 0.0)$$
   > All building footprints remain strictly in their true, unshifted cadastral coordinates. Artificial parallax translation is prohibited because static offsets introduce severe positional errors across variable building heights and disconnect vectors from the elevation grid.
2. **Multi-Modal Feature Fusion:**
   * **NDCI Spectral Index:** $\text{NDCI} = \frac{G - R}{G + R + \epsilon} + 0.5\frac{B - R}{B + R + \epsilon}$
   * **4-Directional GLCM Texture:** Contrast $\sum (i-j)^2 P(i,j \mid \theta)$ and Homogeneity $\sum \frac{P(i,j \mid \theta)}{1+(i-j)^2}$ for $\theta \in \{0^\circ, 45^\circ, 90^\circ, 135^\circ\}$.
   * **2D Gabor Filter Bank:** $E_{\text{Gabor}}(x,y) = \max_{\theta} |L * g_\theta(x,y)|$.
   * **Morphological Top-Hat & Black-Hat:** $T_{\text{white}}(L) = L - (L \circ b_r)$, $T_{\text{black}}(L) = (L \bullet b_r) - L$.
3. **Topological Boolean Subtraction:**
   $$\mathcal{P}_i^{\text{net}} = \text{FilterSlivers}_{A \ge A_{\min}}\left(\mathcal{P}_i^{\text{nadir}} \setminus \bigcup_{k} \mathcal{O}_{i,k}^{\text{nadir}}\right)$$

### 8.2 Section 2 Implementation (`section2_object_detection/run_section2.py`)
```python
"""
section2_object_detection/run_section2.py
Imports rfx_s01_vec_building_footprints.shp and rfx_s01_ras_ortho_rgb.tif from Central Database,
executes multi-modal obstacle detection & shadow disambiguation, and saves:
  - rfx_s02_vec_usable_rooftops.shp & rfx_s02_tbl_usable_area_report.xlsx
  - rfx_s02_vec_physical_obstacles.shp
  - rfx_s02_vec_cast_shadows.shp
"""
import time
import geopandas as gpd
from shapely.affinity import translate

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig
from core_db.database_manager import CentralDatabaseManager
from section2_object_detection.vectorizer_topology import (
    SpatialCropManager,
    UnifiedMultiModalDetector,
    ObstacleShadowVectorizer,
    TopologicalDifferenceEngine,
)


def run_section2(parallax_dx_m: float = 0.0, parallax_dy_m: float = 0.0) -> None:
    """
    Executes Section 2 Object Detection with STRICT ZERO-SHIFT POLICY.
    Building footprints must NEVER be translated or shifted (dx=0.0, dy=0.0).
    """
    # Enforce zero-shift policy
    parallax_dx_m = 0.0
    parallax_dy_m = 0.0

    t0 = time.time()
    config = EcosystemConfig()
    db_mgr = CentralDatabaseManager(config)

    footprints_gdf = db_mgr.load_vector_dataset(
        config.db.s01_footprints_shp, gpkg_layer="s01_building_footprints"
    )
    crop_mgr = SpatialCropManager(config.db.s01_ortho_tif, config.target_crs)
    detector = UnifiedMultiModalDetector(config)
    vectorizer = ObstacleShadowVectorizer(config)
    topo_engine = TopologicalDifferenceEngine(config.min_usable_patch_m2)

    usable_records, obstacle_records, shadow_records = [], [], []

    for _, row in footprints_gdf.iterrows():
        bldg_id = int(row["building_id"])
        nadir_geom = row.geometry

        # STRICT ZERO-SHIFT: Process directly in true georeferenced ground coordinates
        img_geom = nadir_geom
        rgb_crop, win_transform = crop_mgr.crop_polygon_window(img_geom)

        # 2. Multi-Modal CV & Shadow Disambiguation
        det = detector.detect(rgb_crop, img_geom, win_transform)
        phys_objs = vectorizer.extract_obstacles(det, win_transform, bldg_id)
        shd_objs = vectorizer.extract_shadows(det, win_transform, bldg_id)

        # 3. Direct registration (Zero-shift ground coordinates preserved)
        phys_geoms_nadir = []
        cooler_cnt, penth_cnt, vent_cnt = 0, 0, 0
        for obj in phys_objs:
            g_nadir = obj["geometry"]  # Unshifted true geometry
            phys_geoms_nadir.append(g_nadir)
            cls_label = obj["class"]
            if cls_label == "COOLER_AC":
                cooler_cnt += 1
            elif cls_label == "PENTHOUSE":
                penth_cnt += 1
            else:
                vent_cnt += 1
            obstacle_records.append({
                "building_id": bldg_id,
                "obj_class": cls_label,
                "area_m2": round(float(g_nadir.area), 2),
                "geometry": g_nadir,
            })

        shd_geoms_nadir = [shd["geometry"] for shd in shd_objs]
        for shd in shd_objs:
            shadow_records.append({
                "building_id": bldg_id,
                "area_m2": round(float(shd["geometry"].area), 2),
                "geometry": shd["geometry"],
            })
                "area_m2": round(float(g_nadir.area), 2),
                "geometry": g_nadir,
            })

        # 4. Planar Boolean Difference on Nadir Geometry
        net_geom, metrics = topo_engine.subtract_obstacles(nadir_geom, phys_geoms_nadir, shd_geoms_nadir)

        usable_records.append({
            "building_id": bldg_id,
            "gross_area_m2": metrics["orig_area"],
            "obstacle_area_m2": metrics["obj_area"],
            "cast_shadow_area_m2": metrics["shd_area"],
            "usable_area_m2": metrics["net_area"],
            "usable_area_pct": metrics["usable_pct"],
            "obstacle_count": metrics["obj_cnt"],
            "cooler_ac_count": cooler_cnt,
            "penthouse_count": penth_cnt,
            "chimney_vent_count": vent_cnt,
            "parallax_dx_m": parallax_dx_m,
            "parallax_dy_m": parallax_dy_m,
            "suitability_status": metrics["status"],
            "geometry": net_geom,
        })

    usable_gdf = gpd.GeoDataFrame(usable_records, crs=config.target_crs)
    db_mgr.save_vector_dataset(
        usable_gdf,
        shp_path=config.db.s02_usable_rooftops_shp,
        gpkg_layer="s02_usable_rooftops",
        excel_path=config.db.s02_usable_report_xlsx,
    )

    if obstacle_records:
        db_mgr.save_vector_dataset(
            gpd.GeoDataFrame(obstacle_records, crs=config.target_crs),
            shp_path=config.db.s02_obstacles_shp,
            gpkg_layer="s02_physical_obstacles",
        )
    if shadow_records:
        db_mgr.save_vector_dataset(
            gpd.GeoDataFrame(shadow_records, crs=config.target_crs),
            shp_path=config.db.s02_shadows_shp,
            gpkg_layer="s02_cast_shadows",
        )

    print(f"[Section 2] Completed in {time.time() - t0:.2f}s.")
```

---

## 9. Section 3: Main Solar & Energy Engine (Calculations & Code)

### 9.1 Mathematical Formulations
1. **32-Direction Horizon Obstruction Angle ($\alpha_d$) & Sky View Factor ($\text{SVF}$):**
   $$\alpha_d(i, j) = \max_{1 \le m \le M} \arctan2\Big(z(s_m) - z_0,\; s_m\Big) \cdot \frac{180^\circ}{\pi}, \qquad \text{SVF}(i, j) = \frac{1}{32} \sum_{d=0}^{31} \cos^2\Big(\alpha_d(i, j)\Big)$$
2. **Direct & Diffuse Irradiance Integration:**
   $$E(t_k, i, j) = \Delta t \cdot \text{GHI}_{\text{clear}}(t_k) \cdot \Big[ (1 - f_{\text{diff}}) \cdot \mathbb{I}\big(\theta_{\text{alt}}(t_k) \ge \alpha_{d(t_k)}(i, j)\big) + f_{\text{diff}} \cdot \text{SVF}(i, j) \Big]$$
3. **Empirical Zonal Statistics & PV Electricity Yield:**
   $$A_{\text{usable}, i} = \text{Area}(\mathcal{P}_i^{\text{net}}), \qquad E_{\text{PV}, i} = \eta_{\text{PV}} \cdot PR \cdot \frac{\bar{H}_{\text{annual}, i} \cdot A_{\text{usable}, i}}{1000} \quad [\text{MWh/yr}]$$
4. **Local Getis-Ord $G_i^*$ Spatial Clustering:**
   $$G_i^* = \frac{\sum_{j=1}^{N} w_{ij} x_j - \bar{X} \sum_{j=1}^{N} w_{ij}}{S \sqrt{\frac{N \sum_{j=1}^{N} w_{ij}^2 - \left(\sum_{j=1}^{N} w_{ij}\right)^2}{N - 1}}}$$

### 9.2 Section 3 Implementation (`section3_solar_engine/run_section3.py`)
```python
"""
section3_solar_engine/run_section3.py
Imports rfx_s01_ras_synthetic_dsm.tif, rfx_s02_vec_usable_rooftops.shp, and
rfx_s01_vec_building_footprints.shp from Central Database, and saves all standardized
rfx_s03_* rasters, shapefiles, GPKG layers, and Excel reports back to the Central Database.
"""
import math
import time
from esda.getisord import G_Local
import geopandas as gpd
from libpysal.weights import KNN
from numba import njit, prange
import numpy as np
import pandas as pd
import pvlib
from pvlib.irradiance import haurwitz
from pyproj import Transformer
import rasterio
from rasterstats import zonal_stats

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig
from core_db.database_manager import CentralDatabaseManager

DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


@njit(parallel=True, cache=True)
def compute_horizon_32dir_numba(
    dsm: np.ndarray,
    cell_size: float,
    directions: np.ndarray,
    max_distance: float,
    step_size: float,
) -> np.ndarray:
    rows, cols = dsm.shape
    n_dir = directions.shape[0]
    output = np.full((n_dir, rows, cols), -9999.0, dtype=np.float32)
    max_steps = int(max_distance / step_size)

    for i in prange(rows):
        for j in range(cols):
            z0 = dsm[i, j]
            if np.isnan(z0) or z0 <= -9990.0:
                continue
            for d in range(n_dir):
                dx, dy = directions[d, 0], directions[d, 1]
                max_angle = -90.0
                for step in range(1, max_steps + 1):
                    dist = step * step_size
                    x = i + (dy * dist / cell_size)
                    y = j + (dx * dist / cell_size)
                    x0, y0 = int(x), int(y)
                    x1, y1 = x0 + 1, y0 + 1
                    if x0 < 0 or y0 < 0 or x1 >= rows or y1 >= cols:
                        break
                    q11, q21, q12, q22 = dsm[x0, y0], dsm[x1, y0], dsm[x0, y1], dsm[x1, y1]
                    if q11 != q11 or q21 != q21 or q12 != q12 or q22 != q22:
                        continue
                    wx, wy = x - x0, y - y0
                    z = (
                        q11 * (1.0 - wx) * (1.0 - wy)
                        + q21 * wx * (1.0 - wy)
                        + q12 * (1.0 - wx) * wy
                        + q22 * wx * wy
                    )
                    angle = math.degrees(math.atan2(z - z0, dist))
                    if angle > max_angle:
                        max_angle = angle
                    if max_angle >= 89.0:
                        break
                output[d, i, j] = max_angle
    return output


def execute_radiation_simulation(config: EcosystemConfig, db_mgr: CentralDatabaseManager) -> None:
    dsm_path = config.db.s01_synthetic_dsm_tif
    with rasterio.open(dsm_path) as src:
        cx, cy = src.xy(src.height // 2, src.width // 2)
        lon, lat = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True).transform(cx, cy)
        dsm_data = src.read(1).astype(np.float32)
        cell_size = float(src.transform.a)
        base_profile = src.profile.copy()

    times_full = pd.date_range(
        start=f"{config.year}-01-01",
        end=f"{config.year}-12-31 23:59",
        freq=f"{int(config.hour_interval * 60)}min",
        tz=config.timezone,
    )
    times = times_full[times_full.dayofyear % config.day_interval == 0]
    solpos = pvlib.solarposition.get_solarposition(times, lat, lon, altitude=config.altitude_m)
    sun_df = solpos[["zenith", "azimuth"]].copy().reset_index(names="datetime")
    sun_df["datetime"] = pd.to_datetime(sun_df["datetime"], utc=True)
    sun_df["day_of_year"] = sun_df["datetime"].dt.dayofyear
    sun_df["month"] = sun_df["datetime"].dt.month
    sun_df["dir_idx"] = np.round(sun_df["azimuth"] / (360.0 / config.n_directions)).astype(int) % config.n_directions
    sun_df["ghi_clear"] = haurwitz(pd.DatetimeIndex(sun_df["datetime"])).values
    sun_df.to_csv(config.db.s03_solar_geom_csv, index=False)

    dirs = np.array(
        [
            (math.sin(math.radians(d * (360.0 / config.n_directions))),
             -math.cos(math.radians(d * (360.0 / config.n_directions))))
            for d in range(config.n_directions)
        ],
        dtype=np.float32,
    )
    horizon_3d = compute_horizon_32dir_numba(
        dsm_data, cell_size, dirs, config.max_shadow_distance_m, config.ray_step_size_m
    )

    hz_profile = base_profile.copy()
    hz_profile.update(count=config.n_directions, dtype="float32", compress="lzw", nodata=-9999.0)
    with rasterio.open(config.db.s03_horizon_tif, "w", **hz_profile) as dst:
        dst.write(horizon_3d)
    db_mgr.register_raster(config.db.s03_horizon_tif, "s03_horizon_angles_32dir")

    rows, cols = dsm_data.shape
    svf = np.mean(np.cos(np.deg2rad(horizon_3d)) ** 2, axis=0).astype(np.float32)
    single_profile = base_profile.copy()
    single_profile.update(count=1, dtype="float32", compress="lzw", predictor=2, nodata=-9999.0)

    with rasterio.open(config.db.s03_svf_tif, "w", **single_profile) as dst:
        dst.write(svf, 1)
    db_mgr.register_raster(config.db.s03_svf_tif, "s03_sky_view_factor")

    shadow_annual = np.zeros((rows, cols), dtype=np.float32)
    monthly_energy = {m: np.zeros((rows, cols), dtype=np.float32) for m in range(1, 13)}

    for _, srow in sun_df.iterrows():
        sun_alt = float(90.0 - srow["zenith"])
        if sun_alt <= 0.0:
            continue
        band = int(srow["dir_idx"])
        visible = (sun_alt >= horizon_3d[band]).astype(np.float32)
        shadow_annual += 1.0 - visible

        ghi = float(srow["ghi_clear"])
        direct_wh = visible * (ghi * (1.0 - config.diffuse_fraction)) * config.hour_interval
        diffuse_wh = (ghi * config.diffuse_fraction) * svf * config.hour_interval
        monthly_energy[int(srow["month"])] += (direct_wh + diffuse_wh).astype(np.float32)

    annual_kwh = np.zeros((rows, cols), dtype=np.float32)
    for m in range(1, 13):
        n_days = sun_df[sun_df["month"] == m]["day_of_year"].nunique()
        scale = (DAYS_IN_MONTH[m - 1] / n_days) * 1e-3 if n_days > 0 else 0.0
        monthly_energy[m] = (monthly_energy[m] * scale).astype(np.float32)
        annual_kwh += monthly_energy[m]
        m_path = config.db.monthly_rad_tif(m)
        with rasterio.open(m_path, "w", **single_profile) as dst:
            dst.write(monthly_energy[m], 1)

    with rasterio.open(config.db.s03_annual_rad_tif, "w", **single_profile) as dst:
        dst.write(annual_kwh, 1)
    db_mgr.register_raster(config.db.s03_annual_rad_tif, "s03_irradiance_annual")

    with rasterio.open(config.db.s03_shadow_frac_tif, "w", **single_profile) as dst:
        dst.write(shadow_annual, 1)
    db_mgr.register_raster(config.db.s03_shadow_frac_tif, "s03_shadow_fraction_annual")

    suitable_rad = np.where(annual_kwh >= config.min_suitable_rad_kwhm2, annual_kwh, -9999.0).astype(np.float32)
    with rasterio.open(config.db.s03_suitability_tif, "w", **single_profile) as dst:
        dst.write(suitable_rad, 1)
    db_mgr.register_raster(config.db.s03_suitability_tif, "s03_suitability_mask")


def execute_zonal_fusion_and_hotspots(config: EcosystemConfig, db_mgr: CentralDatabaseManager) -> None:
    footprints_gdf = db_mgr.load_vector_dataset(
        config.db.s01_footprints_shp, gpkg_layer="s01_building_footprints"
    )
    usable_gdf = db_mgr.load_vector_dataset(
        config.db.s02_usable_rooftops_shp, gpkg_layer="s02_usable_rooftops"
    )

    meta_cols = footprints_gdf[["building_id", "building_height_m", "num_floors"]].drop_duplicates("building_id")
    gdf = usable_gdf.merge(meta_cols, on="building_id", how="left")

    gdf["usable_area_m2"] = gdf.geometry.area.round(2)
    gdf["usable_area_pct"] = np.where(
        gdf["gross_area_m2"] > 0,
        (gdf["usable_area_m2"] / gdf["gross_area_m2"] * 100.0).round(1),
        0.0,
    )

    stats_ann = zonal_stats(
        gdf.geometry,
        str(config.db.s03_suitability_tif),
        stats=["count", "mean", "min", "max", "std"],
        all_touched=False,
        nodata=-9999.0,
    )
    gdf["suitable_pixel_count"] = [int(s["count"] or 0) for s in stats_ann]
    gdf["mean_kwh_m2_yr"] = [round(float(s["mean"] or 0.0), 2) for s in stats_ann]
    gdf["min_kwh_m2_yr"] = [round(float(s["min"] or 0.0), 2) for s in stats_ann]
    gdf["max_kwh_m2_yr"] = [round(float(s["max"] or 0.0), 2) for s in stats_ann]
    gdf["std_kwh_m2_yr"] = [round(float(s["std"] or 0.0), 2) for s in stats_ann]

    gdf["incident_solar_mwh_yr"] = ((gdf["mean_kwh_m2_yr"] * gdf["usable_area_m2"]) / 1000.0).round(3)
    gdf["installed_capacity_kwp"] = (gdf["usable_area_m2"] * config.pv_efficiency).round(2)
    gdf["elec_yield_mwh_yr"] = (
        config.pv_efficiency * config.performance_ratio * gdf["incident_solar_mwh_yr"]
    ).round(3)

    for m in range(1, 13):
        m_path = config.db.monthly_rad_tif(m)
        m_stats = zonal_stats(gdf.geometry, str(m_path), stats=["mean"], all_touched=False, nodata=-9999.0)
        gdf[f"mean_kwh_m2_m{m:02d}"] = [round(float(s["mean"] or 0.0), 2) for s in m_stats]
        gdf[f"elec_mwh_m{m:02d}"] = (
            config.pv_efficiency
            * config.performance_ratio
            * (gdf[f"mean_kwh_m2_m{m:02d}"] * gdf["usable_area_m2"])
            / 1000.0
        ).round(3)

    db_mgr.save_vector_dataset(
        gdf,
        shp_path=config.db.s03_zonal_stats_shp,
        gpkg_layer="s03_solar_zonal_stats",
    )

    centroids = gdf.geometry.centroid
    coords = np.column_stack([centroids.x, centroids.y])
    k_val = min(config.knn_neighbors, max(1, len(gdf) - 1))
    w = KNN.from_array(coords, k=k_val)
    w.transform = "R"

    y_vals = gdf["elec_yield_mwh_yr"].values.astype(np.float64)
    np.random.seed(42)
    gi = G_Local(y_vals, w, star=True, permutations=config.mc_permutations)

    gdf["gi_star_statistic"] = np.round(gi.Gs, 4)
    gdf["gi_z_score"] = np.round(gi.Zs, 4)
    gdf["gi_p_value"] = np.round(gi.p_sim, 4)

    classes = []
    for z, p in zip(gi.Zs, gi.p_sim):
        if z > 0 and p <= 0.01:
            classes.append("Hot Spot - 99% Confidence")
        elif z > 0 and p <= 0.05:
            classes.append("Hot Spot - 95% Confidence")
        elif z > 0 and p <= 0.10:
            classes.append("Hot Spot - 90% Confidence")
        elif z < 0 and p <= 0.01:
            classes.append("Cold Spot - 99% Confidence")
        elif z < 0 and p <= 0.05:
            classes.append("Cold Spot - 95% Confidence")
        elif z < 0 and p <= 0.10:
            classes.append("Cold Spot - 90% Confidence")
        else:
            classes.append("Not Significant")
    gdf["gi_cluster_class"] = classes

    db_mgr.save_vector_dataset(
        gdf,
        shp_path=config.db.s03_hotspots_final_shp,
        gpkg_layer="s03_solar_hotspots_final",
        excel_path=config.db.s03_solar_final_xlsx,
    )


def run_section3(mode: str = "all") -> None:
    t0 = time.time()
    config = EcosystemConfig()
    db_mgr = CentralDatabaseManager(config)

    if mode in ("all", "radiation_only"):
        execute_radiation_simulation(config, db_mgr)
    if mode in ("all", "fusion_only"):
        execute_zonal_fusion_and_hotspots(config, db_mgr)

    print(f"[Section 3] Completed ({mode}) in {time.time() - t0:.2f}s.")
```

---

## 10. Parallel Orchestration & CLI Execution Manual

```python
"""
run_ecosystem.py
Master Parallel Ecosystem Orchestrator.
"""
from concurrent.futures import ProcessPoolExecutor
import time

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from section1_data_gathering.run_section1 import run_section1
from section2_object_detection.run_section2 import run_section2
from section3_solar_engine.run_section3 import run_section3


def run_ecosystem_parallel() -> None:
    t0 = time.time()
    # 1. Run Section 1 (Populates Central Database with Footprints, Ortho GeoTIFF & Synthetic DSM)
    run_section1()

    # 2. Launch Section 2 (Object Detection) & Section 3 (3D Radiation) simultaneously in parallel
    with ProcessPoolExecutor(max_workers=2) as pool:
        fut_s02 = pool.submit(run_section2)
        fut_s03_rad = pool.submit(run_section3, "radiation_only")
        fut_s02.result()
        fut_s03_rad.result()

    # 3. Fuse Irradiance Rasters with Net Usable Rooftops & compute PV Yield + Hotspots
    run_section3("fusion_only")
    print(f"[Ecosystem] Full parallel run completed in {time.time() - t0:.2f}s.")


if __name__ == "__main__":
    run_ecosystem_parallel()
```

---

## 11. Master Reference Table of Physical & Algorithmic Parameters

| Section | Parameter Name | Default Value | Units | Physical / Algorithmic Role |
| :--- | :--- | :--- | :--- | :--- |
| **Database** | `target_crs` | `EPSG:32639` | meters | Unified metric coordinate reference system enforced across all stores. |
| **Section 1** | `imagery_zoom` | `19` or `20` | zoom level | $\approx 0.298\text{ m/px}$ (Zoom 19) or $\approx 0.149\text{ m/px}$ (Zoom 20) optical resolution. |
| **Section 1** | `min_building_area_m2` | `100.0` | $\text{m}^2$ | Minimum footprint area required for PV installation viability. |
| **Section 1** | `dsm_resolution_m` | `0.50` | $\text{m/px}$ | Grid resolution of `rfx_s01_ras_synthetic_dsm.tif` ($0.25\text{ m}^2\text{/px}$). |
| **Section 2** | `NDCI` | $\frac{G-R}{G+R} + 0.5\frac{B-R}{B+R}$ | dimensionless | Spectral chromaticity index isolating evaporative water coolers. |
| **Section 2** | `GLCM Directions` | $\{0^\circ, 45^\circ, 90^\circ, 135^\circ\}$ | degrees | 4-directional Haralick co-occurrence texture orientations at $d=1$. |
| **Section 2** | `min_obstacle_area_m2` | `0.20` | $\text{m}^2$ | Minimum physical obstacle area retained during vectorization. |
| **Section 2** | `min_usable_patch_m2` | `2.00` | $\text{m}^2$ | Minimum contiguous unobstructed roof patch area required for PV panels. |
| **Section 3** | `day_interval` | `14` | days | Samples 26 representative days across the 365-day year. |
| **Section 3** | `hour_interval` | `0.5` | hours | 30-minute solar integration timestep ($1,248\text{ steps/year}$). |
| **Section 3** | `n_directions` | `32` | sectors | Horizon ray-tracing azimuth bins ($11.25^\circ$ angular resolution). |
| **Section 3** | `max_shadow_distance_m`| `500.0` | meters | Maximum search radius for inter-building shadow ray-tracing. |
| **Section 3** | `diffuse_fraction` | `0.20` | fraction | Isotropic diffuse sky radiation fraction weighted by $\text{SVF}$. |
| **Section 3** | `min_suitable_rad` | `400.0` | $\text{kWh/m}^2\text{/yr}$ | Minimum annual irradiance cutoff for suitable rooftop PV pixels. |
| **Section 3** | `pv_efficiency` ($\eta_{\text{PV}}$) | `0.20` | $20\%$ | Nominal monocrystalline PV module conversion efficiency. |
| **Section 3** | `performance_ratio` ($PR$) | `0.86` | $86\%$ | System performance ratio (inverter, wiring, and thermal losses). |
| **Section 3** | `knn_neighbors` ($K$) | `5` | buildings | K-nearest neighbor spatial weights bandwidth for Local Getis-Ord $G_i^*$. |
| **Section 3** | `mc_permutations` | `999` | runs | Monte Carlo randomizations for hotspot $p$-value significance testing. |
