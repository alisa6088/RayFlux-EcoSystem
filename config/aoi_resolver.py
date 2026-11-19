"""
config/aoi_resolver.py
Universal Case Study Area of Interest (AOI) Resolver.
Accepts any of:
  1. Path to a Vector Shapefile (.shp)
  2. Path to a GeoJSON (.geojson / .json) or GeoPackage (.gpkg)
  3. A 4-tuple / list Bounding Box (west, south, east, north) in EPSG:4326 (or metric UTM)
Computes and standardizes both WGS84 (EPSG:4326) and Metric UTM (e.g., EPSG:32639) extents
and boundary geometries.
"""
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Tuple, Union
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union
from shapely.validation import make_valid

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()


@dataclass
class ResolvedAOI:
    """Standardized spatial extent and boundary geometry for the active Case Study AOI."""

    source_description: str
    target_crs: str
    bbox_wgs84: Tuple[float, float, float, float]       # (west, south, east, north) in EPSG:4326
    bbox_utm: Tuple[float, float, float, float]         # (xmin, ymin, xmax, ymax) in target_crs
    boundary_wgs84: Union[Polygon, MultiPolygon]
    boundary_utm: Union[Polygon, MultiPolygon]
    center_lon: float
    center_lat: float


def infer_utm_epsg_from_lonlat(lon: float, lat: float) -> str:
    """Automatically calculates the standard WGS84 UTM Zone EPSG code from longitude and latitude."""
    zone_number = int((math.floor((lon + 180.0) / 6.0) % 60) + 1)
    epsg_code = (32600 + zone_number) if lat >= 0.0 else (32700 + zone_number)
    return f"EPSG:{epsg_code}"


def resolve_case_study_aoi(
    aoi_input: Union[str, Path, Tuple[float, float, float, float], list],
    target_crs: str | None = None,
    buffer_m: float = 20.0,
) -> ResolvedAOI:
    """Resolves a shapefile, GeoJSON, GeoPackage, or bounding box tuple into a standardized ResolvedAOI."""
    if isinstance(aoi_input, (str, Path)):
        path = Path(aoi_input)
        if not path.exists():
            raise FileNotFoundError(f"Case study AOI file not found: {path}")

        gdf = gpd.read_file(path)
        if gdf.empty:
            raise ValueError(f"Case study AOI file contains no features: {path}")

        if gdf.crs is None:
            gdf.set_crs(epsg=4326, inplace=True)

        # Convert to WGS84 first to inspect center lon/lat
        gdf_wgs84 = gdf.to_crs(epsg=4326)
        w, s, e, n = [float(x) for x in gdf_wgs84.total_bounds]
        center_lon = 0.5 * (w + e)
        center_lat = 0.5 * (s + n)

        resolved_crs = target_crs or infer_utm_epsg_from_lonlat(center_lon, center_lat)
        gdf_utm = gdf.to_crs(resolved_crs)

        # If the input file contains many individual building footprints rather than a single AOI polygon,
        # use the buffered bounding box envelope of the dataset as the study area boundary.
        xmin, ymin, xmax, ymax = [float(x) for x in gdf_utm.total_bounds]
        xmin -= buffer_m
        ymin -= buffer_m
        xmax += buffer_m
        ymax += buffer_m

        if len(gdf_utm) == 1:
            poly_utm = make_valid(gdf_utm.geometry.iloc[0]).buffer(buffer_m)
        else:
            poly_utm = box(xmin, ymin, xmax, ymax)

        poly_wgs84 = gpd.GeoSeries([poly_utm], crs=resolved_crs).to_crs(epsg=4326).iloc[0]
        w, s, e, n = [float(x) for x in poly_wgs84.bounds]

        return ResolvedAOI(
            source_description=f"Vector File ({path.name}, {len(gdf)} features)",
            target_crs=resolved_crs,
            bbox_wgs84=(w, s, e, n),
            bbox_utm=(xmin, ymin, xmax, ymax),
            boundary_wgs84=poly_wgs84,
            boundary_utm=poly_utm,
            center_lon=center_lon,
            center_lat=center_lat,
        )

    elif isinstance(aoi_input, (tuple, list)) and len(aoi_input) == 4:
        c0, c1, c2, c3 = [float(x) for x in aoi_input]
        # Detect whether coordinates are geographic degrees (<= 180) or projected meters (> 180)
        if abs(c0) <= 180.0 and abs(c2) <= 180.0 and abs(c1) <= 90.0 and abs(c3) <= 90.0:
            w, s, e, n = c0, c1, c2, c3
            center_lon = 0.5 * (w + e)
            center_lat = 0.5 * (s + n)
            resolved_crs = target_crs or infer_utm_epsg_from_lonlat(center_lon, center_lat)
            poly_wgs84 = box(w, s, e, n)
            poly_utm = gpd.GeoSeries([poly_wgs84], crs="EPSG:4326").to_crs(resolved_crs).iloc[0]
            xmin, ymin, xmax, ymax = [float(x) for x in poly_utm.bounds]
        else:
            if not target_crs:
                raise ValueError("target_crs must be specified when providing a metric bounding box.")
            resolved_crs = target_crs
            xmin, ymin, xmax, ymax = c0, c1, c2, c3
            poly_utm = box(xmin, ymin, xmax, ymax)
            poly_wgs84 = gpd.GeoSeries([poly_utm], crs=resolved_crs).to_crs("EPSG:4326").iloc[0]
            w, s, e, n = [float(x) for x in poly_wgs84.bounds]
            center_lon = 0.5 * (w + e)
            center_lat = 0.5 * (s + n)

        return ResolvedAOI(
            source_description=f"Bounding Box ({w:.5f}, {s:.5f}, {e:.5f}, {n:.5f})",
            target_crs=resolved_crs,
            bbox_wgs84=(w, s, e, n),
            bbox_utm=(xmin, ymin, xmax, ymax),
            boundary_wgs84=poly_wgs84,
            boundary_utm=poly_utm,
            center_lon=center_lon,
            center_lat=center_lat,
        )

    raise TypeError(f"Unsupported aoi_input type: {type(aoi_input)}. Provide a Path/str (.shp/.geojson) or 4-tuple BBox.")
