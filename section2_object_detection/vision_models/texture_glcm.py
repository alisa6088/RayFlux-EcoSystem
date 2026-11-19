"""
section2_object_detection/vision_models/texture_glcm.py
Vectorized 4-Directional Gray-Level Co-Occurrence Matrix (GLCM) Texture Model.
"""
from typing import Dict, Tuple
import cv2
import numpy as np
from section2_object_detection.cv_config import GLCMConfig


def compute_fast_glcm_features(
    img_gray: np.ndarray, window_size: int = 5, levels: int = 32
) -> Tuple[np.ndarray, np.ndarray]:
    """Computes vectorized directional GLCM Contrast and Homogeneity across 4 orientations (0, 45, 90, 135 deg)."""
    scale_factor = 256 // levels
    q = (img_gray // scale_factor).astype(np.float32)

    diff_0 = np.pad((q[:, 1:] - q[:, :-1]) ** 2, ((0, 0), (0, 1)), mode="edge")
    diff_90 = np.pad((q[1:, :] - q[:-1, :]) ** 2, ((0, 1), (0, 0)), mode="edge")
    diff_45 = np.pad((q[1:, 1:] - q[:-1, :-1]) ** 2, ((0, 1), (0, 1)), mode="edge")
    diff_135 = np.pad((q[1:, :-1] - q[:-1, 1:]) ** 2, ((0, 1), (1, 0)), mode="edge")
    mean_diff = (diff_0 + diff_90 + diff_45 + diff_135) * 0.25

    k = np.ones((window_size, window_size), dtype=np.float32) / (window_size * window_size)
    glcm_contrast = cv2.filter2D(mean_diff, -1, k)

    hom_0 = np.pad(1.0 / (1.0 + (q[:, 1:] - q[:, :-1]) ** 2), ((0, 0), (0, 1)), mode="edge")
    hom_90 = np.pad(1.0 / (1.0 + (q[1:, :] - q[:-1, :]) ** 2), ((0, 1), (0, 0)), mode="edge")
    hom_45 = np.pad(1.0 / (1.0 + (q[1:, 1:] - q[:-1, :-1]) ** 2), ((0, 1), (0, 1)), mode="edge")
    hom_135 = np.pad(1.0 / (1.0 + (q[1:, :-1] - q[:-1, 1:]) ** 2), ((0, 1), (1, 0)), mode="edge")
    mean_hom = (hom_0 + hom_90 + hom_45 + hom_135) * 0.25
    glcm_homogeneity = cv2.filter2D(mean_hom, -1, k)

    return glcm_contrast, glcm_homogeneity


class GLCMTextureModel:
    """Statistical texture analysis model isolating high-frequency equipment variations."""

    def __init__(self, config: GLCMConfig):
        self.config = config

    def extract(self, rgb: np.ndarray, gray: np.ndarray, roof_mask: np.ndarray) -> Dict[str, np.ndarray]:
        if not self.config.enabled:
            return {
                "glcm_contrast": np.zeros(gray.shape, dtype=np.float32),
                "glcm_homogeneity": np.ones(gray.shape, dtype=np.float32),
            }

        con, hom = compute_fast_glcm_features(
            gray,
            window_size=self.config.window_size,
            levels=self.config.levels,
        )
        return {"glcm_contrast": con, "glcm_homogeneity": hom}
