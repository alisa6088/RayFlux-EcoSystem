"""
section3_solar_engine
Solar Physics, 32-Direction Horizon Shading, Monthly & Annual PV Yield,
and Getis-Ord Gi* Spatial Hotspot Engine for the RayFlux Ecosystem.
"""
from section3_solar_engine.solar_config import SolarParameters
from section3_solar_engine.solar_geometry import generate_solar_geometry
from section3_solar_engine.horizon_radiation_engine import run_horizon_and_radiation
from section3_solar_engine.zonal_energy_hotspots import compute_zonal_energy_and_hotspots
from section3_solar_engine.run_section3 import run_section3

__all__ = [
    "SolarParameters",
    "generate_solar_geometry",
    "run_horizon_and_radiation",
    "compute_zonal_energy_and_hotspots",
    "run_section3",
]
