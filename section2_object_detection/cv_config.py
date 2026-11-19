"""
section2_object_detection/cv_config.py
Typed dataclass schema and YAML loader for Section 2 V3 CV hyperparameters.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
import yaml


@dataclass
class CroppingConfig:
    pad_meters: float = 4.0


@dataclass
class ChromaticityConfig:
    enabled: bool = True
    cyan_index_thresh: float = 0.14
    cyan_min_blue: int = 95
    max_cyan_roof_fraction: float = 0.25
    max_cyan_component_pixels: int = 40
    lum_object_min: float = 80.0
    lum_object_max: float = 225.0


@dataclass
class GLCMConfig:
    enabled: bool = True
    window_size: int = 5
    levels: int = 32
    contrast_obj_thresh: float = 26.0
    contrast_shadow_max: float = 20.0
    homogeneity_shadow_min: float = 0.10


@dataclass
class GaborConfig:
    enabled: bool = True
    frequency: float = 0.25
    angles: List[float] = field(default_factory=lambda: [0.0, 0.785398, 1.570796, 2.356194])
    energy_obj_thresh: float = 5.5


@dataclass
class MorphologyConfig:
    enabled: bool = True
    kernel_size: int = 3
    tophat_thresh: int = 32
    blackhat_thresh: int = 32
    gradient_thresh: int = 24


@dataclass
class ShadowConfig:
    enabled: bool = True
    lum_shadow_max: float = 85.0
    max_channel_shadow_max: float = 110.0
    relative_v_ratio: float = 0.68
    contrast_shadow_max: float = 20.0
    homogeneity_shadow_min: float = 0.10
    gabor_energy_max: float = 5.0
    shadow_halo_dilation_px: int = 1
    min_shadow_area_m2: float = 0.50


@dataclass
class OBIAConfig:
    mask_outside_roof_fill: bool = True
    roof_border_erosion_px: int = 2
    morph_close_kernel_size: int = 3
    min_connected_pixels: int = 4
    min_physical_object_area_m2: float = 0.90


@dataclass
class SemanticConfig:
    penthouse_min_area_m2: float = 10.0
    cooler_min_area_m2: float = 1.00


@dataclass
class UsableAreaConfig:
    min_usable_patch_area_m2: float = 2.00
    polygon_simplify_tol_m: float = 0.15


@dataclass
class CVHyperparameters:
    cropping: CroppingConfig = field(default_factory=CroppingConfig)
    chromaticity: ChromaticityConfig = field(default_factory=ChromaticityConfig)
    glcm: GLCMConfig = field(default_factory=GLCMConfig)
    gabor: GaborConfig = field(default_factory=GaborConfig)
    morphology: MorphologyConfig = field(default_factory=MorphologyConfig)
    shadow: ShadowConfig = field(default_factory=ShadowConfig)
    obia: OBIAConfig = field(default_factory=OBIAConfig)
    semantic: SemanticConfig = field(default_factory=SemanticConfig)
    usable_area: UsableAreaConfig = field(default_factory=UsableAreaConfig)

    @classmethod
    def load_yaml(cls, yaml_path: Path) -> "CVHyperparameters":
        if not yaml_path.exists():
            return cls()
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        return cls(
            cropping=CroppingConfig(**raw.get("cropping", {})),
            chromaticity=ChromaticityConfig(**raw.get("chromaticity", {})),
            glcm=GLCMConfig(**raw.get("glcm", {})),
            gabor=GaborConfig(**raw.get("gabor", {})),
            morphology=MorphologyConfig(**raw.get("morphology", {})),
            shadow=ShadowConfig(**raw.get("shadow", {})),
            obia=OBIAConfig(**raw.get("obia", {})),
            semantic=SemanticConfig(**raw.get("semantic", {})),
            usable_area=UsableAreaConfig(**raw.get("usable_area", {})),
        )
