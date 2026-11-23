"""
core_db/init_postgis_cluster.py
Initializes and starts a dedicated PostgreSQL + PostGIS spatial database cluster
for the RayFlux Ecosystem, saves portable relative credentials to `.env` and
`database/core/rfx_db_postgis_credentials.json`, enables the PostGIS extension,
and syncs vector layers into PostGIS.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Optional
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import to_project_relative_posix

CLUSTER_DIR = PROJECT_ROOT / "database" / "postgis_cluster"
PG_LOG_FILE = PROJECT_ROOT / "logs" / "postgis_server.log"
CREDENTIALS_JSON = PROJECT_ROOT / "database" / "core" / "rfx_db_postgis_credentials.json"
ENV_FILE = PROJECT_ROOT / ".env"

PG_HOST = os.getenv("RFX_PG_HOST", "127.0.0.1")
PG_PORT = int(os.getenv("RFX_PG_PORT", "5433"))
PG_USER = os.getenv("RFX_PG_USER", "rayflux_admin")
PG_PASSWORD = os.getenv("RFX_PG_PASSWORD", "RayFlux_2026_Pass")
PG_DATABASE = os.getenv("RFX_PG_DATABASE", "rayflux_spatial_db")
PG_SCHEMA = os.getenv("RFX_PG_SCHEMA", "public")


def _pg_exe_name(base: str) -> str:
    return f"{base}.exe" if os.name == "nt" else base


def discover_postgres_bin_dir() -> Path:
    """Dynamically discovers the PostgreSQL `bin/` directory containing `initdb` and `pg_ctl`
    from `RFX_PG_BIN_DIR`, system PATH, or standard cross-platform installation directories."""
    initdb_name = _pg_exe_name("initdb")

    env_bin = os.getenv("RFX_PG_BIN_DIR")
    if env_bin and (Path(env_bin) / initdb_name).exists():
        return Path(env_bin)

    which_initdb = shutil.which("initdb")
    if which_initdb:
        return Path(which_initdb).resolve().parent

    # Cross-platform standard installation discovery (Windows, Linux, macOS)
    candidate_roots = []
    if os.name == "nt":
        anchor_drive = Path(PROJECT_ROOT.anchor)
        candidate_roots.extend([
            anchor_drive / "postgresql16.8" / "install" / "bin",
            anchor_drive / "postgresql" / "install" / "bin",
            Path(os.environ.get("ProgramFiles", "")) / "PostgreSQL",
        ])
    else:
        candidate_roots.extend([
            Path("/usr/lib/postgresql"),
            Path("/usr/local/pgsql/bin"),
            Path("/opt/homebrew/opt"),
            Path("/usr/local/opt"),
            Path("/Applications/Postgres.app/Contents/Versions/latest/bin"),
        ])

    for cand in candidate_roots:
        if (cand / initdb_name).exists():
            return cand
        if cand.exists() and cand.is_dir():
            for pattern in ("*/bin", "postgresql*/bin"):
                for sub in sorted(cand.glob(pattern), reverse=True):
                    if (sub / initdb_name).exists():
                        return sub

    raise FileNotFoundError(
        "PostgreSQL binaries (`initdb`, `pg_ctl`) not found. Set `RFX_PG_BIN_DIR` in `.env` or add PostgreSQL `bin/` to PATH."
    )


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) == 0


def ensure_postgis_cluster_running() -> dict:
    """Initializes the dedicated PostgreSQL + PostGIS cluster if not yet created,
    starts the server on port 5433, and ensures `rayflux_spatial_db` + `postgis` extension exist."""
    PG_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_JSON.parent.mkdir(parents=True, exist_ok=True)

    pg_bin_dir = discover_postgres_bin_dir()
    initdb_exe = pg_bin_dir / _pg_exe_name("initdb")
    pg_ctl_exe = pg_bin_dir / _pg_exe_name("pg_ctl")

    # 1. Initialize cluster if PG_VERSION does not exist
    pg_version_file = CLUSTER_DIR / "PG_VERSION"
    if not pg_version_file.exists():
        print(f"[PostGIS Setup] Initializing new PostgreSQL cluster at: {to_project_relative_posix(CLUSTER_DIR)}")
        CLUSTER_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as pwf:
            pwf.write(PG_PASSWORD + "\n")
            pwfile_path = pwf.name

        try:
            cmd_init = [
                str(initdb_exe),
                "-D", str(CLUSTER_DIR),
                "-U", PG_USER,
                f"--pwfile={pwfile_path}",
                "-E", "UTF8",
                "--locale=C",
                "-A", "scram-sha-256",
            ]
            subprocess.run(cmd_init, check=True, capture_output=True, text=True)
        finally:
            Path(pwfile_path).unlink(missing_ok=True)

        conf_file = CLUSTER_DIR / "postgresql.conf"
        with open(conf_file, "a", encoding="utf-8") as f:
            f.write("\n# RayFlux Dedicated PostGIS Configuration\n")
            f.write(f"listen_addresses = '{PG_HOST}'\n")
            f.write(f"port = {PG_PORT}\n")
            f.write("max_connections = 100\n")
            f.write("shared_buffers = 256MB\n")

    # 2. Start PostgreSQL cluster if not already listening on PG_PORT
    if not is_port_open(PG_HOST, PG_PORT):
        print(f"[PostGIS Setup] Starting PostgreSQL server on {PG_HOST}:{PG_PORT}...")
        cmd_start = [
            str(pg_ctl_exe),
            "-D", str(CLUSTER_DIR),
            "-l", str(PG_LOG_FILE),
            "-o", f"-p {PG_PORT} -h {PG_HOST}",
            "-w",
            "start",
        ]
        subprocess.run(
            cmd_start,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
    else:
        print(f"[PostGIS Setup] PostgreSQL server is already active on {PG_HOST}:{PG_PORT}.")

    # 3. Create `rayflux_spatial_db` and enable `postgis` extension
    admin_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/postgres"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": PG_DATABASE}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{PG_DATABASE}" OWNER "{PG_USER}"'))
            print(f"[PostGIS Setup] Created spatial database: {PG_DATABASE}")
    admin_engine.dispose()

    db_url = f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"
    db_engine = create_engine(db_url)
    with db_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        postgis_ver = conn.execute(text("SELECT PostGIS_Full_Version()")).scalar()
        print(f"[PostGIS Setup] Enabled PostGIS Extension: {postgis_ver[:80]}...")
    db_engine.dispose()

    # 4. Save portable relative credentials to JSON & .env
    creds = {
        "host": PG_HOST,
        "port": PG_PORT,
        "database": PG_DATABASE,
        "schema": PG_SCHEMA,
        "user": PG_USER,
        "password": PG_PASSWORD,
        "sqlalchemy_url": db_url,
        "cluster_dir": to_project_relative_posix(CLUSTER_DIR),
        "log_file": to_project_relative_posix(PG_LOG_FILE),
    }
    CREDENTIALS_JSON.write_text(json.dumps(creds, indent=2), encoding="utf-8")

    env_content = (
        f"RFX_PG_HOST={PG_HOST}\n"
        f"RFX_PG_PORT={PG_PORT}\n"
        f"RFX_PG_DATABASE={PG_DATABASE}\n"
        f"RFX_PG_SCHEMA={PG_SCHEMA}\n"
        f"RFX_PG_USER={PG_USER}\n"
        f"RFX_PG_PASSWORD={PG_PASSWORD}\n"
    )
    ENV_FILE.write_text(env_content, encoding="utf-8")
    print(f"[PostGIS Setup] Saved portable credentials to: {to_project_relative_posix(CREDENTIALS_JSON)} and .env")
    return creds


if __name__ == "__main__":
    ensure_postgis_cluster_running()

    from config.ecosystem_config import EcosystemConfig
    from core_db.database_manager import CentralDatabaseManager
    import geopandas as gpd

    cfg = EcosystemConfig()
    db_mgr = CentralDatabaseManager(cfg)
    if cfg.db.s01_footprints_shp.exists():
        gdf = gpd.read_file(cfg.db.master_gpkg, layer="s01_building_footprints")
        db_mgr.save_vector_dataset(
            gdf,
            shp_path=cfg.db.s01_footprints_shp,
            gpkg_layer="s01_building_footprints",
            excel_path=cfg.db.s01_inventory_xlsx,
        )
        if cfg.db.s01_synthetic_dsm_tif.exists():
            db_mgr.register_raster(cfg.db.s01_synthetic_dsm_tif, "s01_synthetic_dsm")
        if cfg.db.s01_ortho_tif.exists():
            db_mgr.register_raster(cfg.db.s01_ortho_tif, "s01_ortho_rgb")

        engine = db_mgr.get_postgis_engine()
        with engine.connect() as conn:
            res = conn.execute(
                text(
                    "SELECT COUNT(*) AS cnt, ST_SRID(geometry) AS srid, "
                    "ROUND(AVG(building_height_m)::numeric, 2) AS avg_h "
                    "FROM public.s01_building_footprints GROUP BY ST_SRID(geometry)"
                )
            ).fetchone()
            print(
                f"[PostGIS Verified] Table `public.s01_building_footprints` -> "
                f"Rows: {res[0]}, SRID: EPSG:{res[1]}, Avg Height: {res[2]}m"
            )
