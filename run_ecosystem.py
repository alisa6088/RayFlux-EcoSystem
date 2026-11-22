"""
run_ecosystem.py
Master CLI Orchestrator for the RayFlux Solar Intelligence Ecosystem.

Runs all three decoupled geospatial engines sequentially or independently against the
Central Geospatial Database (PostgreSQL/PostGIS + Master GeoPackage + Tiled GeoTIFFs + Excel):

  Examples:
    python run_ecosystem.py --status
    python run_ecosystem.py --all
    python run_ecosystem.py --section 1 --aoi data/case_study_aoi/rfx_aoi_boundary.shp
    python run_ecosystem.py --section 2 --workers 8
    python run_ecosystem.py --section 3 --reuse-rasters
"""
import argparse
import json
from pathlib import Path
import sys
import time
from typing import List, Tuple, Union

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig, to_project_relative_posix


def _parse_aoi_arg(aoi_str: str) -> Union[Path, Tuple[float, float, float, float]]:
    """Parses either a file path (.shp/.geojson/.gpkg) or a 'west,south,east,north' WGS84 bbox."""
    parts = [p.strip() for p in aoi_str.split(",")]
    if len(parts) == 4:
        try:
            return tuple(float(p) for p in parts)  # type: ignore[return-value]
        except ValueError:
            pass
    p = Path(aoi_str)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


def print_ecosystem_status(cfg: EcosystemConfig) -> None:
    """Displays the current Central Geospatial Database asset catalog status."""
    print("=" * 76)
    print("  RAYFLUX SOLAR INTELLIGENCE ECOSYSTEM — DATABASE ASSET STATUS")
    print("=" * 76)
    print(f"  Project Root : .")
    print(f"  PostGIS DSN  : postgresql://{cfg.postgis.user}:***@{cfg.postgis.host}:{cfg.postgis.port}/{cfg.postgis.database}")
    print(f"  Active AOI   : {to_project_relative_posix(cfg.aoi_source) if isinstance(cfg.aoi_source, Path) else cfg.aoi_source}")
    print("-" * 76)

    if not cfg.db.catalog_json.exists():
        print("  Asset catalog not initialized yet. Run `--section 1` or `--all`.")
        print("=" * 76)
        return

    catalog = json.loads(cfg.db.catalog_json.read_text(encoding="utf-8"))
    for key, meta in catalog.items():
        kind = meta.get("kind", "unknown").upper()
        if kind == "VECTOR":
            pg_flag = "PostGIS=OK" if meta.get("postgis_synced") else "PostGIS=OFF"
            print(
                f"  [VECTOR] {key:<26s} | rows={meta.get('feature_count', 0):>6,} | "
                f"{meta.get('crs', 'N/A'):<10s} | {pg_flag}"
            )
        elif kind == "RASTER":
            res = meta.get("resolution", [0, 0])
            print(
                f"  [RASTER] {key:<26s} | {meta.get('width', 0):>5}x{meta.get('height', 0):<5} "
                f"({meta.get('bands', 1)}b, {res[0]:.2f}m) | {meta.get('crs', 'N/A')}"
            )
        else:
            print(f"  [{kind:<6s}] {key}")
    print("=" * 76)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RayFlux Solar Intelligence Ecosystem — Master Pipeline Orchestrator",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run Sections 1, 2, and 3 end-to-end sequentially.",
    )
    parser.add_argument(
        "--section",
        type=int,
        choices=[1, 2, 3],
        action="append",
        help="Run specific section(s) (repeatable, e.g. --section 2 --section 3).",
    )
    parser.add_argument(
        "--aoi",
        type=str,
        default=None,
        help="Override Case Study AOI: path to .shp/.geojson/.gpkg or 'west,south,east,north' WGS84 bbox.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker process count for Section 2 multi-modal CV (default: auto up to 8).",
    )
    parser.add_argument(
        "--reuse-rasters",
        action="store_true",
        help="Section 3: reuse existing horizon/irradiance GeoTIFF rasters and recompute zonal stats, PV yield, Gi* & maps.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print Central Geospatial Database asset catalog status and exit.",
    )

    args = parser.parse_args()
    cfg = EcosystemConfig()
    if args.aoi:
        cfg.aoi_source = _parse_aoi_arg(args.aoi)

    if args.status or (not args.all and not args.section):
        print_ecosystem_status(cfg)
        if not args.status:
            print("\nTip: pass `--all` or `--section 1|2|3` to execute pipeline stages (see `--help`).")
        return 0

    sections: List[int] = [1, 2, 3] if args.all else sorted(set(args.section))
    t_total = time.time()

    print("=" * 76)
    print(f"  RAYFLUX ECOSYSTEM ORCHESTRATOR — EXECUTING SECTIONS: {sections}")
    print("=" * 76)

    for sec in sections:
        if sec == 1:
            from section1_data_gathering.run_section1 import run_section1
            run_section1(cfg)
        elif sec == 2:
            from section2_object_detection.run_section2 import run_section2
            run_section2(cfg, max_workers=args.workers)
        elif sec == 3:
            from section3_solar_engine.run_section3 import run_section3
            run_section3(cfg, reuse_existing_rasters=args.reuse_rasters)

    print("=" * 76)
    print(f"  RAYFLUX ECOSYSTEM RUN COMPLETE in {time.time() - t_total:.1f}s")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
