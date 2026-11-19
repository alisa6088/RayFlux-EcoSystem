"""
section2_object_detection/vision_models/shadow_disambiguator.py
Physics-Informed Rooftop Shadow Disambiguation Engine (V3).
"""
import cv2
import numpy as np
from section2_object_detection.cv_config import ShadowConfig


class ShadowDisambiguationEngine:
    """Distinguishes flat radiometric cast shadows from 3D physical rooftop obstacles."""

    def __init__(self, config: ShadowConfig):
        self.config = config
        self.close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    def detect_shadows(
        self,
        luminance: np.ndarray,
        glcm_contrast: np.ndarray,
        glcm_homogeneity: np.ndarray,
        gabor_energy: np.ndarray,
        roof_mask: np.ndarray,
        max_rgb: np.ndarray = None,
    ) -> np.ndarray:
        if not self.config.enabled:
            return np.zeros(roof_mask.shape, dtype=np.uint8)

        is_dark = luminance < self.config.lum_shadow_max
        if max_rgb is not None:
            roof_vals = max_rgb[roof_mask > 0]
            if roof_vals.size > 0:
                sunlit_ref_v = float(np.percentile(roof_vals, 75))
                adaptive_v_thresh = min(
                    float(self.config.max_channel_shadow_max),
                    sunlit_ref_v * float(self.config.relative_v_ratio),
                )
            else:
                adaptive_v_thresh = float(self.config.max_channel_shadow_max)
            is_dark = is_dark & (max_rgb < adaptive_v_thresh)

        raw_shadow = (
            is_dark
            & (glcm_contrast <= self.config.contrast_shadow_max)
            & (glcm_homogeneity >= self.config.homogeneity_shadow_min)
            & (gabor_energy < self.config.gabor_energy_max)
            & (roof_mask > 0)
        )

        closed_shadow = cv2.morphologyEx(
            raw_shadow.astype(np.uint8), cv2.MORPH_CLOSE, self.close_kernel
        )
        return closed_shadow
