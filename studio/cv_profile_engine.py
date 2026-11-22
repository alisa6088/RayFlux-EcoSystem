"""
studio/cv_profile_engine.py
Smart Regional CV Hyperparameter Synthesizer & YAML Profile Manager for Section 2.

Takes multi-select urban/area typology checkboxes (industrial, residential, dense_residential,
commercial, mixed_urban, rural, institutional) + roof/imagery characteristics (painted metal roofs,
pitched/gable roofs, high-density coolers, heavy parapet shadows, imagery GSD m/px) and synthesizes
a physically calibrated, schema-validated `cv_hyperparameters.yaml` file stored under `config/profiles/`.
"""
from dataclasses import asdict
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import yaml

from config.ecosystem_config import PROJECT_ROOT, to_project_relative_posix
from section2_object_detection.cv_config import CVHyperparameters

PROFILES_DIR = PROJECT_ROOT / "config" / "profiles"
DEFAULT_CV_YAML = PROJECT_ROOT / "config" / "cv_hyperparameters.yaml"

# Scientifically calibrated physical archetype templates (at nominal ~0.35-0.48 m/px baseline)
AREA_TYPE_ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "industrial": {
        "label": "Industrial Park / Factories / Warehouses",
        "description": "Large metal/corrugated shed roofs, skylights, HVAC banks, painted blue/red/green sheets.",
        "params": {
            "pad_meters": 4.0,
            "cyan_index_thresh": 0.14,
            "cyan_min_blue": 95,
            "max_cyan_roof_fraction": 0.25,
            "max_cyan_component_m2": 9.5,
            "lum_object_min": 80.0,
            "lum_object_max": 225.0,
            "glcm_window": 5,
            "contrast_obj_thresh": 26.0,
            "gabor_energy_thresh": 5.5,
            "tophat_thresh": 32,
            "blackhat_thresh": 32,
            "gradient_thresh": 24,
            "lum_shadow_max": 85.0,
            "max_channel_shadow_max": 110.0,
            "relative_v_ratio": 0.68,
            "shadow_halo_px": 1,
            "setback_m": 1.0,
            "min_object_area_m2": 0.90,
            "penthouse_min_area_m2": 10.0,
            "cooler_min_area_m2": 1.0,
            "min_usable_patch_m2": 2.0,
        },
    },
    "residential": {
        "label": "Suburban / Low-Rise Residential",
        "description": "Medium flat/pitched homes with evaporative coolers, water tanks, chimneys, staircases.",
        "params": {
            "pad_meters": 3.0,
            "cyan_index_thresh": 0.09,
            "cyan_min_blue": 80,
            "max_cyan_roof_fraction": 0.35,
            "max_cyan_component_m2": 12.0,
            "lum_object_min": 75.0,
            "lum_object_max": 230.0,
            "glcm_window": 5,
            "contrast_obj_thresh": 22.0,
            "gabor_energy_thresh": 4.8,
            "tophat_thresh": 28,
            "blackhat_thresh": 28,
            "gradient_thresh": 20,
            "lum_shadow_max": 88.0,
            "max_channel_shadow_max": 115.0,
            "relative_v_ratio": 0.70,
            "shadow_halo_px": 1,
            "setback_m": 0.55,
            "min_object_area_m2": 0.40,
            "penthouse_min_area_m2": 6.0,
            "cooler_min_area_m2": 0.75,
            "min_usable_patch_m2": 1.5,
        },
    },
    "dense_residential": {
        "label": "Dense Urban / Mid-to-High-Rise Apartments",
        "description": "Compact cluttered roofs with elevator bulkheads, dense AC/cooler clusters & deep parapet shadows.",
        "params": {
            "pad_meters": 3.0,
            "cyan_index_thresh": 0.08,
            "cyan_min_blue": 75,
            "max_cyan_roof_fraction": 0.40,
            "max_cyan_component_m2": 10.0,
            "lum_object_min": 72.0,
            "lum_object_max": 232.0,
            "glcm_window": 5,
            "contrast_obj_thresh": 20.0,
            "gabor_energy_thresh": 4.4,
            "tophat_thresh": 25,
            "blackhat_thresh": 26,
            "gradient_thresh": 19,
            "lum_shadow_max": 92.0,
            "max_channel_shadow_max": 118.0,
            "relative_v_ratio": 0.72,
            "shadow_halo_px": 1,
            "setback_m": 0.45,
            "min_object_area_m2": 0.30,
            "penthouse_min_area_m2": 5.0,
            "cooler_min_area_m2": 0.65,
            "min_usable_patch_m2": 1.2,
        },
    },
    "commercial": {
        "label": "Commercial / Malls / Office Complexes",
        "description": "Large flat concrete/membrane roofs with central chillers, ducts, skylights & mechanical screens.",
        "params": {
            "pad_meters": 4.0,
            "cyan_index_thresh": 0.12,
            "cyan_min_blue": 88,
            "max_cyan_roof_fraction": 0.30,
            "max_cyan_component_m2": 12.0,
            "lum_object_min": 78.0,
            "lum_object_max": 228.0,
            "glcm_window": 5,
            "contrast_obj_thresh": 24.0,
            "gabor_energy_thresh": 5.0,
            "tophat_thresh": 30,
            "blackhat_thresh": 30,
            "gradient_thresh": 22,
            "lum_shadow_max": 86.0,
            "max_channel_shadow_max": 112.0,
            "relative_v_ratio": 0.68,
            "shadow_halo_px": 1,
            "setback_m": 0.85,
            "min_object_area_m2": 0.65,
            "penthouse_min_area_m2": 9.0,
            "cooler_min_area_m2": 0.90,
            "min_usable_patch_m2": 2.0,
        },
    },
    "mixed_urban": {
        "label": "Mixed-Use Urban District",
        "description": "Balanced configuration spanning retail halls, mid-rise apartments, and service workshops.",
        "params": {
            "pad_meters": 3.5,
            "cyan_index_thresh": 0.11,
            "cyan_min_blue": 85,
            "max_cyan_roof_fraction": 0.32,
            "max_cyan_component_m2": 10.5,
            "lum_object_min": 76.0,
            "lum_object_max": 228.0,
            "glcm_window": 5,
            "contrast_obj_thresh": 23.0,
            "gabor_energy_thresh": 4.9,
            "tophat_thresh": 29,
            "blackhat_thresh": 29,
            "gradient_thresh": 21,
            "lum_shadow_max": 87.0,
            "max_channel_shadow_max": 114.0,
            "relative_v_ratio": 0.69,
            "shadow_halo_px": 1,
            "setback_m": 0.70,
            "min_object_area_m2": 0.55,
            "penthouse_min_area_m2": 7.5,
            "cooler_min_area_m2": 0.85,
            "min_usable_patch_m2": 1.6,
        },
    },
    "rural": {
        "label": "Rural / Agricultural / Barns & Greenhouses",
        "description": "Isolated simple barns/structures with low obstacle density and strong surround vegetation contrast.",
        "params": {
            "pad_meters": 4.0,
            "cyan_index_thresh": 0.15,
            "cyan_min_blue": 98,
            "max_cyan_roof_fraction": 0.22,
            "max_cyan_component_m2": 8.0,
            "lum_object_min": 82.0,
            "lum_object_max": 224.0,
            "glcm_window": 5,
            "contrast_obj_thresh": 28.0,
            "gabor_energy_thresh": 5.8,
            "tophat_thresh": 34,
            "blackhat_thresh": 34,
            "gradient_thresh": 26,
            "lum_shadow_max": 82.0,
            "max_channel_shadow_max": 106.0,
            "relative_v_ratio": 0.65,
            "shadow_halo_px": 1,
            "setback_m": 1.0,
            "min_object_area_m2": 1.00,
            "penthouse_min_area_m2": 12.0,
            "cooler_min_area_m2": 1.20,
            "min_usable_patch_m2": 2.5,
        },
    },
    "institutional": {
        "label": "Institutional / Hospitals / Universities",
        "description": "Large multi-wing campuses with heliports, mechanical penthouses, ducts & courtyard roofs.",
        "params": {
            "pad_meters": 4.0,
            "cyan_index_thresh": 0.12,
            "cyan_min_blue": 88,
            "max_cyan_roof_fraction": 0.30,
            "max_cyan_component_m2": 12.0,
            "lum_object_min": 78.0,
            "lum_object_max": 228.0,
            "glcm_window": 5,
            "contrast_obj_thresh": 23.0,
            "gabor_energy_thresh": 5.0,
            "tophat_thresh": 29,
            "blackhat_thresh": 29,
            "gradient_thresh": 21,
            "lum_shadow_max": 86.0,
            "max_channel_shadow_max": 112.0,
            "relative_v_ratio": 0.68,
            "shadow_halo_px": 1,
            "setback_m": 0.80,
            "min_object_area_m2": 0.60,
            "penthouse_min_area_m2": 9.0,
            "cooler_min_area_m2": 0.90,
            "min_usable_patch_m2": 2.0,
        },
    },
}

ROOF_TRAIT_OPTIONS: Dict[str, Dict[str, str]] = {
    "painted_metal_roofs": {
        "label": "Painted Metal / Colored Corrugated Roofs (Red / Blue / Green)",
        "effect": "Tightens NDCI paint guards & HSV Value shadow ceiling to stop colored metal sheets from triggering.",
    },
    "pitched_gable_roofs": {
        "label": "Pitched / Gable Roof Slopes",
        "effect": "Tightens relative_v_ratio so shaded roof slopes are never mistaken for cast shadows.",
    },
    "dense_coolers_hvac": {
        "label": "High-Density Evaporative Coolers / Rooftop HVAC",
        "effect": "Increases NDCI & Top-Hat sensitivity to capture compact coolers & small AC units.",
    },
    "heavy_parapet_shadows": {
        "label": "Tall Parapet Walls & Deep Cast Shadows",
        "effect": "Expands shadow halo suppression and raises contrast ceiling for clean shadow disambiguation.",
    },
    "corrugated_striping": {
        "label": "High-Frequency Corrugated Metal Striping",
        "effect": "Slightly raises Gabor & gradient thresholds to ignore repetitive roof-rib textures.",
    },
}


def sanitize_profile_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip().lower()).strip("_")
    return slug or "custom_profile"


def synthesize_cv_config(
    area_types: List[str],
    traits: Optional[List[str]] = None,
    imagery_gsd_m: float = 0.48,
    profile_name: str = "custom_area",
) -> Dict[str, Any]:
    """Synthesizes an optimized, physically scaled CVHyperparameters dict + commented YAML string."""
    selected = [t for t in area_types if t in AREA_TYPE_ARCHETYPES]
    if not selected:
        selected = ["mixed_urban"]
    traits_set = set(traits or [])
    gsd = max(0.10, min(1.50, float(imagery_gsd_m)))

    # 1. Blend selected area-type archetypes equally
    keys = list(AREA_TYPE_ARCHETYPES[selected[0]]["params"].keys())
    blended: Dict[str, float] = {}
    for k in keys:
        blended[k] = sum(float(AREA_TYPE_ARCHETYPES[t]["params"][k]) for t in selected) / len(selected)

    # 2. Apply roof & imagery trait modifiers
    if "painted_metal_roofs" in traits_set:
        blended["cyan_index_thresh"] = max(blended["cyan_index_thresh"], 0.14)
        blended["cyan_min_blue"] = max(blended["cyan_min_blue"], 95.0)
        blended["max_cyan_roof_fraction"] = min(blended["max_cyan_roof_fraction"], 0.25)
        blended["max_channel_shadow_max"] = min(blended["max_channel_shadow_max"], 108.0)

    if "pitched_gable_roofs" in traits_set:
        blended["relative_v_ratio"] = min(blended["relative_v_ratio"], 0.64)
        blended["lum_shadow_max"] = min(blended["lum_shadow_max"], 82.0)

    if "dense_coolers_hvac" in traits_set:
        blended["cyan_index_thresh"] = max(0.07, blended["cyan_index_thresh"] - 0.03)
        blended["contrast_obj_thresh"] = max(18.0, blended["contrast_obj_thresh"] - 3.0)
        blended["tophat_thresh"] = max(22.0, blended["tophat_thresh"] - 4.0)
        blended["min_object_area_m2"] = max(0.25, blended["min_object_area_m2"] * 0.80)

    if "heavy_parapet_shadows" in traits_set:
        blended["shadow_halo_px"] = max(blended["shadow_halo_px"], 2.0)
        blended["lum_shadow_max"] = min(98.0, blended["lum_shadow_max"] + 6.0)
        blended["max_channel_shadow_max"] = min(122.0, blended["max_channel_shadow_max"] + 6.0)

    if "corrugated_striping" in traits_set:
        blended["gabor_energy_thresh"] += 0.8
        blended["gradient_thresh"] += 3.0
        blended["contrast_obj_thresh"] += 2.5

    # 3. Physical pixel scaling from imagery GSD (m/px)
    px_area = gsd * gsd
    min_connected_pixels = max(2, int(math.ceil(blended["min_object_area_m2"] / px_area)))
    max_cyan_component_pixels = max(15, int(round(blended["max_cyan_component_m2"] / px_area)))
    roof_border_erosion_px = max(1, min(4, int(round(blended["setback_m"] / gsd))))
    glcm_window = 7 if gsd <= 0.22 else 5
    morph_close = 5 if gsd <= 0.22 else 3

    config_dict = {
        "cropping": {
            "pad_meters": round(blended["pad_meters"], 2),
        },
        "chromaticity": {
            "enabled": True,
            "cyan_index_thresh": round(blended["cyan_index_thresh"], 3),
            "cyan_min_blue": int(round(blended["cyan_min_blue"])),
            "max_cyan_roof_fraction": round(blended["max_cyan_roof_fraction"], 2),
            "max_cyan_component_pixels": int(max_cyan_component_pixels),
            "lum_object_min": round(blended["lum_object_min"], 1),
            "lum_object_max": round(blended["lum_object_max"], 1),
        },
        "glcm": {
            "enabled": True,
            "window_size": int(glcm_window),
            "levels": 32,
            "contrast_obj_thresh": round(blended["contrast_obj_thresh"], 1),
            "contrast_shadow_max": 20.0,
            "homogeneity_shadow_min": 0.10,
        },
        "gabor": {
            "enabled": True,
            "frequency": 0.25,
            "angles": [0.0, 0.785398, 1.570796, 2.356194],
            "energy_obj_thresh": round(blended["gabor_energy_thresh"], 2),
        },
        "morphology": {
            "enabled": True,
            "kernel_size": 3,
            "tophat_thresh": int(round(blended["tophat_thresh"])),
            "blackhat_thresh": int(round(blended["blackhat_thresh"])),
            "gradient_thresh": int(round(blended["gradient_thresh"])),
        },
        "shadow": {
            "enabled": True,
            "lum_shadow_max": round(blended["lum_shadow_max"], 1),
            "max_channel_shadow_max": round(blended["max_channel_shadow_max"], 1),
            "relative_v_ratio": round(blended["relative_v_ratio"], 2),
            "contrast_shadow_max": 20.0,
            "homogeneity_shadow_min": 0.10,
            "gabor_energy_max": 5.0,
            "shadow_halo_dilation_px": int(round(blended["shadow_halo_px"])),
            "min_shadow_area_m2": 0.50,
        },
        "obia": {
            "mask_outside_roof_fill": True,
            "roof_border_erosion_px": int(roof_border_erosion_px),
            "morph_close_kernel_size": int(morph_close),
            "min_connected_pixels": int(min_connected_pixels),
            "min_physical_object_area_m2": round(blended["min_object_area_m2"], 2),
        },
        "semantic": {
            "penthouse_min_area_m2": round(blended["penthouse_min_area_m2"], 1),
            "cooler_min_area_m2": round(blended["cooler_min_area_m2"], 2),
        },
        "usable_area": {
            "min_usable_patch_area_m2": round(blended["min_usable_patch_m2"], 2),
            "polygon_simplify_tol_m": 0.15,
        },
    }

    header = (
        f"# ==============================================================================\n"
        f"# RAYFLUX SECTION 2 — AUTO-SYNTHESIZED CV PROFILE: {profile_name}\n"
        f"# ==============================================================================\n"
        f"# Area Types : {', '.join(selected)}\n"
        f"# Roof Traits: {', '.join(sorted(traits_set)) if traits_set else 'none'}\n"
        f"# Target GSD : {gsd:.2f} m/px (1 px = {px_area:.3f} m²)\n"
        f"# ==============================================================================\n\n"
    )
    yaml_text = header + yaml.safe_dump(config_dict, sort_keys=False, default_flow_style=False)
    return {
        "profile_name": sanitize_profile_slug(profile_name),
        "area_types": selected,
        "traits": sorted(traits_set),
        "imagery_gsd_m": gsd,
        "config": config_dict,
        "yaml_text": yaml_text,
    }


def validate_cv_yaml_text(yaml_text: str) -> Dict[str, Any]:
    """Validates raw YAML text strictly against Section 2 `CVHyperparameters` dataclass schema."""
    raw = yaml.safe_load(yaml_text)
    if not isinstance(raw, dict):
        raise ValueError("YAML root must be a key-value mapping.")
    # Write/load validation through exact CVHyperparameters constructor
    from section2_object_detection.cv_config import (
        ChromaticityConfig,
        CroppingConfig,
        GaborConfig,
        GLCMConfig,
        MorphologyConfig,
        OBIAConfig,
        SemanticConfig,
        ShadowConfig,
        UsableAreaConfig,
    )
    parsed = CVHyperparameters(
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
    return asdict(parsed)


def ensure_default_profiles() -> None:
    """Seeds standard ready-to-use regional CV YAML profiles inside `config/profiles/`."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    seeds = [
        ("industrial", ["industrial"], ["painted_metal_roofs", "corrugated_striping"], 0.48),
        ("residential", ["residential"], ["dense_coolers_hvac"], 0.30),
        ("dense_residential", ["dense_residential"], ["dense_coolers_hvac", "heavy_parapet_shadows"], 0.30),
        ("mixed_urban", ["mixed_urban"], [], 0.40),
    ]
    for name, a_types, traits, gsd in seeds:
        target = PROFILES_DIR / f"{name}.yaml"
        if not target.exists():
            res = synthesize_cv_config(a_types, traits=traits, imagery_gsd_m=gsd, profile_name=name)
            target.write_text(res["yaml_text"], encoding="utf-8")


def list_profiles() -> List[Dict[str, Any]]:
    """Lists the master default YAML + all saved regional profiles in `config/profiles/`."""
    ensure_default_profiles()
    profiles: List[Dict[str, Any]] = []
    if DEFAULT_CV_YAML.exists():
        profiles.append({
            "id": "default",
            "name": "Active Default (cv_hyperparameters.yaml)",
            "path": to_project_relative_posix(DEFAULT_CV_YAML),
            "is_default": True,
            "yaml_text": DEFAULT_CV_YAML.read_text(encoding="utf-8"),
        })
    for p in sorted(PROFILES_DIR.glob("*.yaml")):
        profiles.append({
            "id": p.stem,
            "name": p.stem.replace("_", " ").title(),
            "path": to_project_relative_posix(p),
            "is_default": False,
            "yaml_text": p.read_text(encoding="utf-8"),
        })
    return profiles


def save_profile(profile_name: str, yaml_text: str, set_as_default: bool = False) -> Dict[str, Any]:
    """Validates and saves a CV YAML profile into `config/profiles/<slug>.yaml`."""
    validate_cv_yaml_text(yaml_text)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    slug = sanitize_profile_slug(profile_name)
    out_path = PROFILES_DIR / f"{slug}.yaml"
    out_path.write_text(yaml_text, encoding="utf-8")
    if set_as_default:
        DEFAULT_CV_YAML.write_text(yaml_text, encoding="utf-8")
    return {
        "id": slug,
        "path": to_project_relative_posix(out_path),
        "set_as_default": set_as_default,
    }


def resolve_profile_path(profile_id: Optional[str]) -> Path:
    """Resolves a profile ID or relative path to an absolute YAML file path."""
    if not profile_id or profile_id == "default":
        return DEFAULT_CV_YAML
    cand = PROFILES_DIR / f"{sanitize_profile_slug(profile_id)}.yaml"
    if cand.exists():
        return cand
    direct = PROJECT_ROOT / profile_id
    if direct.exists():
        return direct
    return DEFAULT_CV_YAML
