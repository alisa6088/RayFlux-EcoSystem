"""
section2_object_detection/vectorizer_topology.py
Window cropping (without parallax shifting), polygon vectorization, semantic obstacle
classification, and topological Boolean difference (`Gross Roof - Physical Obstacles`).
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.windows import from_bounds
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from section2_object_detection.cv_config import CVHyperparameters


class OrthoWindowCropper:
    """Extracts padded RGB raster crop windows directly in the unified metric CRS (no parallax shift)."""

    def __init__(self, ortho_tif_path: Path, pad_meters: float = 4.0):
        self.ortho_tif_path = Path(ortho_tif_path)
        self.pad_meters = pad_meters
        self.src = rasterio.open(self.ortho_tif_path)

    def crop_building(self, geom: Any) -> Tuple[np.ndarray, Any]:
        minx, miny, maxx, maxy = geom.bounds
        win = from_bounds(
            minx - self.pad_meters,
            miny - self.pad_meters,
            maxx + self.pad_meters,
            maxy + self.pad_meters,
            transform=self.src.transform,
        )
        win = win.round_offsets().round_lengths()
        rgb = self.src.read([1, 2, 3], window=win, boundless=True, fill_value=0)
        rgb = np.transpose(rgb, (1, 2, 0)).astype(np.uint8)
        win_transform = self.src.window_transform(win)
        return rgb, win_transform

    def close(self) -> None:
        if self.src and not self.src.closed:
            self.src.close()


class ObstacleVectorizer:
    """Converts binary pixel masks into simplified, semantically classified Shapely polygons."""

    def __init__(self, params: CVHyperparameters):
        self.min_obj_area = params.obia.min_physical_object_area_m2
        self.min_shadow_area = params.shadow.min_shadow_area_m2
        self.simplify_tol = params.usable_area.polygon_simplify_tol_m
        self.penthouse_thresh = params.semantic.penthouse_min_area_m2
        self.cooler_thresh = params.semantic.cooler_min_area_m2

    def vectorize_obstacles(self, physical_mask: np.ndarray, win_transform: Any, building_id: int) -> List[Dict[str, Any]]:
        if physical_mask.sum() == 0:
            return []

        items = []
        for geom_dict, val in shapes(physical_mask, mask=(physical_mask == 1), transform=win_transform):
            if val != 1:
                continue
            poly = shape(geom_dict)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue

            sub_polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
            for p in sub_polys:
                if p.area < self.min_obj_area:
                    continue
                p_clean = p.simplify(self.simplify_tol, preserve_topology=True)
                if not p_clean.is_valid or p_clean.is_empty:
                    p_clean = p

                area = float(p_clean.area)
                if area >= self.penthouse_thresh:
                    obj_class, conf = "PENTHOUSE", 0.95
                elif area >= self.cooler_thresh:
                    obj_class, conf = "COOLER_AC", 0.92
                else:
                    obj_class, conf = "CHIMNEY_VENT", 0.88

                items.append({
                    "building_id": int(building_id),
                    "obj_class": obj_class,
                    "area_m2": round(area, 2),
                    "conf": conf,
                    "geometry": p_clean,
                })
        return items

    def vectorize_shadows(self, shadow_mask: np.ndarray, win_transform: Any, building_id: int) -> List[Dict[str, Any]]:
        if shadow_mask.sum() == 0:
            return []

        items = []
        for geom_dict, val in shapes(shadow_mask, mask=(shadow_mask == 1), transform=win_transform):
            if val != 1:
                continue
            poly = shape(geom_dict)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.is_empty:
                continue

            sub_polys = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
            for p in sub_polys:
                if p.area < self.min_shadow_area:
                    continue
                p_clean = p.simplify(self.simplify_tol, preserve_topology=True)
                if not p_clean.is_valid or p_clean.is_empty:
                    p_clean = p

                items.append({
                    "building_id": int(building_id),
                    "obj_class": "SHADOW",
                    "area_m2": round(float(p_clean.area), 2),
                    "geometry": p_clean,
                })
        return items


class RooftopSpatialEngine:
    """Computes topological difference (`Gross Roof - Union(Physical Obstacles)`) and usable metrics."""

    def __init__(self, min_usable_patch_m2: float = 2.0):
        self.min_usable_patch_m2 = min_usable_patch_m2

    def subtract_physical_objects(
        self,
        building_geom: Any,
        physical_obj_geoms: List[Any],
        shadow_geoms: Optional[List[Any]] = None,
    ) -> Tuple[Any, Dict[str, Any]]:
        if not building_geom.is_valid:
            building_geom = make_valid(building_geom)

        orig_area = float(building_geom.area)
        valid_objs = [make_valid(g) for g in physical_obj_geoms if g is not None and not g.is_empty]
        valid_objs = [g for g in valid_objs if g.is_valid and not g.is_empty]

        valid_shds = []
        if shadow_geoms:
            valid_shds = [make_valid(g) for g in shadow_geoms if g is not None and not g.is_empty]
            valid_shds = [g for g in valid_shds if g.is_valid and not g.is_empty]
        shd_area = float(unary_union(valid_shds).area) if valid_shds else 0.0

        if not valid_objs:
            return building_geom, {
                "orig_area": round(orig_area, 2),
                "obj_area": 0.0,
                "shd_area": round(shd_area, 2),
                "net_area": round(orig_area, 2),
                "usable_pct": 100.0,
                "obj_cnt": 0,
                "status": "EXCELLENT",
            }

        obj_union = make_valid(unary_union(valid_objs))
        try:
            diff_geom = building_geom.difference(obj_union)
        except Exception:
            diff_geom = make_valid(building_geom).difference(make_valid(obj_union))
        if not diff_geom.is_valid:
            diff_geom = make_valid(diff_geom)

        filtered = []
        if diff_geom.geom_type == "Polygon":
            if diff_geom.area >= self.min_usable_patch_m2:
                filtered.append(diff_geom)
        elif diff_geom.geom_type == "MultiPolygon":
            filtered = [p for p in diff_geom.geoms if p.area >= self.min_usable_patch_m2]
        elif diff_geom.geom_type == "GeometryCollection":
            filtered = [g for g in diff_geom.geoms if isinstance(g, Polygon) and g.area >= self.min_usable_patch_m2]

        if not filtered:
            clean_net = Polygon()
            net_area = 0.0
        elif len(filtered) == 1:
            clean_net = filtered[0]
            net_area = float(clean_net.area)
        else:
            clean_net = MultiPolygon(filtered)
            net_area = float(clean_net.area)

        obj_area = max(0.0, orig_area - net_area)
        usable_pct = (net_area / orig_area * 100.0) if orig_area > 0 else 0.0
        status = (
            "EXCELLENT" if usable_pct >= 60.0
            else "GOOD" if usable_pct >= 40.0
            else "MODERATE" if usable_pct >= 20.0
            else "LIMITED"
        )

        return clean_net, {
            "orig_area": round(orig_area, 2),
            "obj_area": round(obj_area, 2),
            "shd_area": round(shd_area, 2),
            "net_area": round(net_area, 2),
            "usable_pct": round(usable_pct, 1),
            "obj_cnt": len(valid_objs),
            "status": status,
        }
