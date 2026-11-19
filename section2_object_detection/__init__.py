"""
section2_object_detection
Multi-modal deterministic V3 Rooftop Object Detection Engine (No Parallax) for the RayFlux Ecosystem.
"""
from section2_object_detection.cv_config import CVHyperparameters
from section2_object_detection.vectorizer_topology import (
    ObstacleVectorizer,
    OrthoWindowCropper,
    RooftopSpatialEngine,
)
from section2_object_detection.vision_models import UnifiedRooftopDetector
from section2_object_detection.run_section2 import run_section2

__all__ = [
    "CVHyperparameters",
    "OrthoWindowCropper",
    "ObstacleVectorizer",
    "RooftopSpatialEngine",
    "UnifiedRooftopDetector",
    "run_section2",
]
