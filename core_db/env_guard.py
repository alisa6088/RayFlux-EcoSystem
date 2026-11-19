"""
core_db/env_guard.py
Isolates Python's internal PROJ/GDAL database from conflicting system variables
(such as PostgreSQL/PostGIS or OSGeo4W) on Windows.
"""
import os
import warnings
import pyproj


def initialize_spatial_env() -> str:
    """Binds PROJ_LIB and PROJ_DATA strictly to pyproj's internal validated database."""
    os.environ.pop("PROJ_LIB", None)
    os.environ.pop("PROJ_DATA", None)
    proj_data_dir = pyproj.datadir.get_data_dir()
    os.environ["PROJ_LIB"] = proj_data_dir
    os.environ["PROJ_DATA"] = proj_data_dir
    os.environ["GDAL_PAM_ENABLED"] = "NO"
    warnings.filterwarnings("ignore", category=UserWarning)
    return proj_data_dir
