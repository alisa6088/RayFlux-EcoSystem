"""
section3_solar_engine/solar_config.py
Typed dataclass schema and YAML loader for Section 3 solar physics, PV yield, and hotspot parameters.
"""
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class SolarGeometryConfig:
    year: int = 2024
    timezone: str = "UTC"
    day_interval: int = 14
    hour_interval: float = 0.5
    altitude_m: float = 1200.0
    clear_sky_model: str = "haurwitz"
    atmospheric_clearness_kt: float = 1.00
    diffuse_fraction: float = 0.20


@dataclass
class HorizonConfig:
    n_directions: int = 32
    max_distance_m: float = 500.0
    step_size_m: float = 1.0
    rooftop_only_mask: bool = True
    tile_size: int = 512


@dataclass
class SuitabilityConfig:
    min_annual_rad_kwhm2: float = 400.0


@dataclass
class PVSystemConfig:
    pv_efficiency: float = 0.20
    performance_ratio: float = 0.86
    use_section2_usable_polygons: bool = True
    fallback_usable_ratio: float = 0.70


@dataclass
class HotspotConfig:
    k_neighbors: int = 10
    weights_type: str = "gaussian_kernel"
    value_transform: str = "sqrt"
    star: bool = True
    p_value_method: str = "analytical"
    permutations: int = 999
    random_seed: int = 42


@dataclass
class SolarParameters:
    solar_geometry: SolarGeometryConfig = field(default_factory=SolarGeometryConfig)
    horizon: HorizonConfig = field(default_factory=HorizonConfig)
    suitability: SuitabilityConfig = field(default_factory=SuitabilityConfig)
    pv_system: PVSystemConfig = field(default_factory=PVSystemConfig)
    hotspots: HotspotConfig = field(default_factory=HotspotConfig)

    @classmethod
    def load_yaml(cls, yaml_path: Path) -> "SolarParameters":
        if not yaml_path.exists():
            return cls()
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        return cls(
            solar_geometry=SolarGeometryConfig(**raw.get("solar_geometry", {})),
            horizon=HorizonConfig(**raw.get("horizon", {})),
            suitability=SuitabilityConfig(**raw.get("suitability", {})),
            pv_system=PVSystemConfig(**raw.get("pv_system", {})),
            hotspots=HotspotConfig(**raw.get("hotspots", {})),
        )
