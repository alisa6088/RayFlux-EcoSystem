"""
core_db/verify_setup.py
Initializes and verifies the RayFlux Ecosystem directory structure, database folders,
PROJ/GDAL isolation, virtual environment, and all required libraries using portable project-relative paths.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.ecosystem_config import EcosystemConfig, to_project_relative_posix
from core_db.database_manager import CentralDatabaseManager


REQUIRED_LIBRARIES = [
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("pandas", "pandas"),
    ("numba", "numba"),
    ("pyproj", "pyproj"),
    ("shapely", "shapely"),
    ("fiona", "fiona"),
    ("geopandas", "geopandas"),
    ("rasterio", "rasterio"),
    ("pyarrow", "pyarrow"),
    ("overturemaps", "overturemaps"),
    ("mercantile", "mercantile"),
    ("contextily", "contextily"),
    ("opencv-python", "cv2"),
    ("scikit-image", "skimage"),
    ("scikit-learn", "sklearn"),
    ("pvlib", "pvlib"),
    ("rasterstats", "rasterstats"),
    ("libpysal", "libpysal"),
    ("esda", "esda"),
    ("openpyxl", "openpyxl"),
    ("pyyaml", "yaml"),
    ("requests", "requests"),
    ("Pillow", "PIL"),
    ("matplotlib", "matplotlib"),
    ("tqdm", "tqdm"),
]


def verify_and_init() -> None:
    print("=" * 75)
    print("RAYFLUX SOLAR ECOSYSTEM — ENVIRONMENT & DIRECTORY VERIFICATION")
    print("=" * 75)

    cfg = EcosystemConfig()
    db_mgr = CentralDatabaseManager(cfg)
    db_mgr._log_audit("VERIFY_SETUP", "database", "Verified standardized rfx_* directories and environment")
    print(f"[OK] Central Database root verified at: {to_project_relative_posix(cfg.db.master_gpkg.parent.parent)}")

    venv_dir = PROJECT_ROOT / ".venv"
    if not venv_dir.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir), "--system-site-packages"], check=True)
        print(f"[OK] Created project virtual environment at: {to_project_relative_posix(venv_dir)}")
    else:
        print(f"[OK] Project virtual environment verified at: {to_project_relative_posix(venv_dir)}")

    missing = [pkg for pkg, mod in REQUIRED_LIBRARIES if importlib.util.find_spec(mod) is None]
    print(f"[OK] Verified {len(REQUIRED_LIBRARIES) - len(missing)}/{len(REQUIRED_LIBRARIES)} required libraries.")
    if missing:
        print(f"[WARNING] Missing packages: {missing}")
    else:
        print("[OK] All 26 geospatial, computer vision, and solar physics libraries are active!")


if __name__ == "__main__":
    verify_and_init()
