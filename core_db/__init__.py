"""RayFlux Core Database & Spatial Environment Guard Package."""
from core_db.env_guard import initialize_spatial_env

__all__ = ["initialize_spatial_env", "CentralDatabaseManager", "SHP_COLUMN_MAP", "INV_SHP_COLUMN_MAP"]


def __getattr__(name: str):
    if name in ("CentralDatabaseManager", "SHP_COLUMN_MAP", "INV_SHP_COLUMN_MAP"):
        from core_db import database_manager
        return getattr(database_manager, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
