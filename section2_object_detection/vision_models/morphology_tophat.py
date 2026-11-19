"""
section2_object_detection/vision_models/morphology_tophat.py
Multi-Scale Morphological Gradient, White Top-Hat & Black-Hat Anomaly Model.
"""
from typing import Dict
import cv2
import numpy as np
from section2_object_detection.cv_config import MorphologyConfig


class MorphologyGradientModel:
    """Detects localized specular peaks (vent caps) and dark flue/pipe openings."""

    def __init__(self, config: MorphologyConfig):
        self.config = config
        self.kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (self.config.kernel_size, self.config.kernel_size)
        )

    def extract(self, rgb: np.ndarray, gray: np.ndarray, roof_mask: np.ndarray) -> Dict[str, np.ndarray]:
        if not self.config.enabled:
            return {
                "tophat": np.zeros(gray.shape, dtype=np.uint8),
                "blackhat": np.zeros(gray.shape, dtype=np.uint8),
                "morph_grad": np.zeros(gray.shape, dtype=np.uint8),
                "is_vent_anomaly": np.zeros(gray.shape, dtype=bool),
            }

        tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, self.kernel)
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, self.kernel)
        morph_grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, self.kernel)

        is_vent_anomaly = (
            (tophat > self.config.tophat_thresh) | (blackhat > self.config.blackhat_thresh)
        ) & (roof_mask > 0)

        return {
            "tophat": tophat,
            "blackhat": blackhat,
            "morph_grad": morph_grad,
            "is_vent_anomaly": is_vent_anomaly,
        }
