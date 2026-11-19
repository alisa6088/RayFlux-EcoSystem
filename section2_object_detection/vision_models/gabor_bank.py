"""
section2_object_detection/vision_models/gabor_bank.py
Multi-Orientation 2D Gabor Filter Bank Model.
"""
from typing import Dict
import numpy as np
from skimage.filters import gabor
from section2_object_detection.cv_config import GaborConfig


class GaborFilterModel:
    """Computes multi-angle frequency energy to detect elevated mechanical boundary transitions."""

    def __init__(self, config: GaborConfig):
        self.config = config

    def extract(self, rgb: np.ndarray, gray: np.ndarray, roof_mask: np.ndarray) -> Dict[str, np.ndarray]:
        if not self.config.enabled:
            return {"gabor_energy": np.zeros(gray.shape, dtype=np.float32)}

        energies = []
        for theta in self.config.angles:
            real, imag = gabor(gray, frequency=self.config.frequency, theta=theta)
            energies.append(np.sqrt(real ** 2 + imag ** 2))

        mean_energy = np.mean(energies, axis=0).astype(np.float32)
        return {"gabor_energy": mean_energy}
