"""
section2_object_detection/vision_models/chromaticity_ndci.py
Optical RGB Chromaticity & Normalized Difference Cyan Index (NDCI) Model.
"""
from typing import Dict
import cv2
import numpy as np
from section2_object_detection.cv_config import ChromaticityConfig


class ChromaticityModel:
    """Detects spectral characteristics of rooftop equipment using chromatic ratios."""

    def __init__(self, config: ChromaticityConfig):
        self.config = config

    def extract(self, rgb: np.ndarray, gray: np.ndarray, roof_mask: np.ndarray) -> Dict[str, np.ndarray]:
        if not self.config.enabled:
            return {
                "is_cyan_cooler": np.zeros(gray.shape, dtype=bool),
                "luminance": gray.astype(np.float32),
            }

        r = rgb[:, :, 0].astype(np.float32)
        g = rgb[:, :, 1].astype(np.float32)
        b = rgb[:, :, 2].astype(np.float32)

        luminance = (r + g + b) / 3.0
        cyan_index = (b - r) / (b + r + 1e-5)

        is_cyan_cooler = (
            (cyan_index > self.config.cyan_index_thresh)
            & (b > self.config.cyan_min_blue)
            & (roof_mask > 0)
        )

        # Guard 1: Industrial roof paint guard — if cyan covers > max_cyan_roof_fraction of the roof,
        # the roof itself is painted blue/cyan metal rather than containing a localized cooler.
        roof_pixels = int((roof_mask > 0).sum())
        if roof_pixels > 0 and (is_cyan_cooler.sum() / roof_pixels) > self.config.max_cyan_roof_fraction:
            is_cyan_cooler = np.zeros(gray.shape, dtype=bool)
        elif is_cyan_cooler.any() and self.config.max_cyan_component_pixels > 0:
            # Guard 2: Localized component guard — any single cyan blob larger than max_cyan_component_pixels
            # is a painted roof panel / skylight sheet rather than an evaporative cooler.
            nb_cc, labels, stats, _ = cv2.connectedComponentsWithStats(is_cyan_cooler.astype(np.uint8), connectivity=8)
            filtered_cyan = np.zeros(gray.shape, dtype=bool)
            for idx in range(1, nb_cc):
                if stats[idx, cv2.CC_STAT_AREA] <= self.config.max_cyan_component_pixels:
                    filtered_cyan[labels == idx] = True
            is_cyan_cooler = filtered_cyan

        return {
            "cyan_index": cyan_index,
            "is_cyan_cooler": is_cyan_cooler,
            "luminance": luminance,
        }
