"""
section2_object_detection/vision_models/unified_detector.py
Unified Multi-Modal Rooftop Detector (V3 — No Parallax).
Fuses NDCI chromaticity, 4-directional GLCM texture, multi-angle Gabor energy,
morphological Top-Hat/Black-Hat anomalies, and physics-informed shadow disambiguation.
"""
from typing import Any, Dict
import cv2
import numpy as np
from rasterio.features import rasterize
from shapely.geometry.base import BaseGeometry

from section2_object_detection.cv_config import CVHyperparameters
from section2_object_detection.vision_models.chromaticity_ndci import ChromaticityModel
from section2_object_detection.vision_models.gabor_bank import GaborFilterModel
from section2_object_detection.vision_models.morphology_tophat import MorphologyGradientModel
from section2_object_detection.vision_models.shadow_disambiguator import ShadowDisambiguationEngine
from section2_object_detection.vision_models.texture_glcm import GLCMTextureModel


class UnifiedRooftopDetector:
    """Master V3 multi-modal detector isolating physical rooftop obstacles from cast shadows."""

    def __init__(self, params: CVHyperparameters):
        self.params = params
        self.chromaticity_model = ChromaticityModel(params.chromaticity)
        self.glcm_model = GLCMTextureModel(params.glcm)
        self.gabor_model = GaborFilterModel(params.gabor)
        self.morphology_model = MorphologyGradientModel(params.morphology)
        self.shadow_engine = ShadowDisambiguationEngine(params.shadow)
        self.close_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (params.obia.morph_close_kernel_size, params.obia.morph_close_kernel_size),
        )

    def process_roof(self, rgb_img: np.ndarray, roof_geometry: Any, win_transform: Any) -> Dict[str, Any]:
        h, w = rgb_img.shape[:2]

        if isinstance(roof_geometry, BaseGeometry) or hasattr(roof_geometry, "geom_type"):
            roof_mask = rasterize(
                [(roof_geometry, 1)],
                out_shape=(h, w),
                transform=win_transform,
                fill=0,
                dtype=np.uint8,
            )
        else:
            roof_mask = (roof_geometry > 0).astype(np.uint8)

        if roof_mask.sum() == 0:
            zeros = np.zeros((h, w), dtype=np.uint8)
            zeros_f = np.zeros((h, w), dtype=np.float32)
            return {
                "physical_objects_mask": zeros,
                "shadows_mask": zeros,
                "all_obstructions_mask": zeros,
                "glcm_contrast": zeros_f,
                "glcm_homogeneity": zeros_f,
                "gabor_energy": zeros_f,
                "roof_mask": zeros,
            }

        gray = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2GRAY)

        # Roof-interior background fill: replace off-roof pixels (road, yard, trees) with the
        # roof's own median grayscale value before running spatial kernels (GLCM, Gabor, Morphology).
        # This eliminates off-roof contrast bleeding across the roof perimeter on every building.
        if self.params.obia.mask_outside_roof_fill:
            roof_median_gray = int(np.median(gray[roof_mask > 0]))
            gray_spatial = np.where(roof_mask > 0, gray, roof_median_gray).astype(np.uint8)
        else:
            gray_spatial = gray

        chroma_res = self.chromaticity_model.extract(rgb_img, gray, roof_mask)
        is_cyan_cooler = chroma_res["is_cyan_cooler"]
        luminance = chroma_res["luminance"]

        glcm_res = self.glcm_model.extract(rgb_img, gray_spatial, roof_mask)
        glcm_con = glcm_res["glcm_contrast"]
        glcm_hom = glcm_res["glcm_homogeneity"]

        gabor_res = self.gabor_model.extract(rgb_img, gray_spatial, roof_mask)
        gabor_ene = gabor_res["gabor_energy"]

        morph_res = self.morphology_model.extract(rgb_img, gray_spatial, roof_mask)
        is_vent_anomaly = morph_res["is_vent_anomaly"]
        morph_grad = morph_res["morph_grad"]

        max_rgb = rgb_img.max(axis=2).astype(np.float32)
        raw_shadow = self.shadow_engine.detect_shadows(
            luminance=luminance,
            glcm_contrast=glcm_con,
            glcm_homogeneity=glcm_hom,
            gabor_energy=gabor_ene,
            roof_mask=roof_mask,
            max_rgb=max_rgb,
        )

        # Inward roof-edge erosion prevents off-roof ground/road/parapet contrast from bleeding
        # inside the roof perimeter through the 5x5 GLCM and 3x3 gradient/Gabor kernels.
        erosion_px = max(0, int(self.params.obia.roof_border_erosion_px))
        if erosion_px > 0:
            erode_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * erosion_px + 1, 2 * erosion_px + 1))
            interior_mask = cv2.erode(roof_mask, erode_k)
            if interior_mask.sum() < 16:
                interior_mask = roof_mask
        else:
            interior_mask = roof_mask

        # Rule A: High texture contrast on elevated physical body (interior only)
        textured_body = (
            (glcm_con > self.params.glcm.contrast_obj_thresh)
            & (luminance >= self.params.chromaticity.lum_object_min)
            & (luminance < self.params.chromaticity.lum_object_max)
            & (interior_mask == 1)
        )

        # Rule B: Structural boundaries with high Gabor energy and morphological gradient (interior only)
        structural_boundary = (
            (gabor_ene >= self.params.gabor.energy_obj_thresh)
            & (morph_grad > self.params.morphology.gradient_thresh)
            & (interior_mask == 1)
        )

        # Shadow-edge halo suppression: dilate cast shadows slightly so the bright-to-dark
        # transition rim of a cast shadow does not trigger false gradient/contrast obstacles.
        halo_px = max(0, int(self.params.shadow.shadow_halo_dilation_px))
        if halo_px > 0 and raw_shadow.any():
            halo_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * halo_px + 1, 2 * halo_px + 1))
            shadow_exclusion = cv2.dilate(raw_shadow.astype(np.uint8), halo_k) > 0
        else:
            shadow_exclusion = raw_shadow > 0

        raw_physical = (
            is_cyan_cooler | textured_body | (is_vent_anomaly & (interior_mask == 1)) | structural_boundary
        ) & (~shadow_exclusion) & (interior_mask == 1)

        closed_physical = cv2.morphologyEx(
            raw_physical.astype(np.uint8), cv2.MORPH_CLOSE, self.close_kernel
        )

        min_pixels = self.params.obia.min_connected_pixels
        nb_cc, labels, stats, _ = cv2.connectedComponentsWithStats(closed_physical, connectivity=8)
        clean_physical = np.zeros_like(closed_physical)
        for i in range(1, nb_cc):
            if stats[i, cv2.CC_STAT_AREA] >= min_pixels:
                clean_physical[labels == i] = 1

        all_obstructions = ((clean_physical == 1) | (raw_shadow == 1)).astype(np.uint8)

        return {
            "physical_objects_mask": clean_physical.astype(np.uint8),
            "shadows_mask": raw_shadow.astype(np.uint8),
            "all_obstructions_mask": all_obstructions,
            "glcm_contrast": glcm_con.astype(np.float32),
            "glcm_homogeneity": glcm_hom.astype(np.float32),
            "gabor_energy": gabor_ene.astype(np.float32),
            "roof_mask": roof_mask.astype(np.uint8),
        }
