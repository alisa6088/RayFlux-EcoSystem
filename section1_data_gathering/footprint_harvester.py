"""
section1_data_gathering/footprint_harvester.py
Harvests 3D LoD1 building footprints and structural height attributes from the
TUM Global 3D WFS service for any resolved Case Study AOI, cleans geometries,
projects to the metric target CRS, and assigns the immutable primary key `building_id`.
"""
import time
from typing import List, Optional
import urllib3
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.validation import make_valid

from core_db.env_guard import initialize_spatial_env
initialize_spatial_env()

from config.aoi_resolver import ResolvedAOI
from config.ecosystem_config import EcosystemConfig

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TUM3DFootprintHarvester:
    """Automated WFS harvester for the TUM Global 3D LoD1 building database."""

    def __init__(self, config: EcosystemConfig):
        self.config = config
        self.base_url = config.tum_wfs_base_url.rstrip("/")
        self.grid_step = config.tum_grid_step_deg
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"{self.base_url}/",
            "Connection": "keep-alive",
        }
        self._viewer_token: Optional[str] = None
        self._requests_on_token: int = 0
        self._max_requests_per_token: int = 180

    def _obtain_viewer_session_token(self) -> str:
        """Automatically requests a fresh viewerSession token from the TUM WFS endpoint."""
        url = f"{self.base_url}/viewer-session"
        res = self.session.get(url, headers=self.headers, verify=False, timeout=20)
        res.raise_for_status()
        data = res.json()
        token = data.get("viewerSession")
        if not token:
            raise RuntimeError(f"Failed to obtain viewerSession token from {url}: {data}")
        self._viewer_token = token
        self._requests_on_token = 0
        self._max_requests_per_token = max(10, int(data.get("maxWfsRequests", 200)) - 15)
        return token

    def _get_active_token(self, force_refresh: bool = False) -> str:
        if force_refresh or not self._viewer_token or self._requests_on_token >= self._max_requests_per_token:
            return self._obtain_viewer_session_token()
        return self._viewer_token

    def harvest_aoi_footprints(self, aoi: ResolvedAOI) -> gpd.GeoDataFrame:
        """Downloads all 3D LoD1 buildings inside the resolved AOI bounding box,
        deduplicates edge-crossing buildings, cleans topology, and assigns `building_id`."""
        min_x, min_y, max_x, max_y = aoi.bbox_wgs84

        x_coords = np.arange(min_x, max_x, self.grid_step)
        y_coords = np.arange(min_y, max_y, self.grid_step)
        if len(x_coords) == 0 or x_coords[-1] < max_x:
            x_coords = np.append(x_coords, max_x)
        if len(y_coords) == 0 or y_coords[-1] < max_y:
            y_coords = np.append(y_coords, max_y)

        total_tiles = (len(x_coords) - 1) * (len(y_coords) - 1)
        print(f"[Section 1 | Footprints] Querying TUM 3D LoD1 WFS across {total_tiles} grid tile(s)...")

        all_gdfs: List[gpd.GeoDataFrame] = []
        tile_idx = 0

        for i in range(len(x_coords) - 1):
            for j in range(len(y_coords) - 1):
                tile_idx += 1
                tx0, ty0, tx1, ty1 = x_coords[i], y_coords[j], x_coords[i + 1], y_coords[j + 1]

                for attempt in range(3):
                    token = self._get_active_token(force_refresh=(attempt > 0))
                    wfs_url = (
                        f"{self.base_url}/geoserver/ows?"
                        "service=WFS&version=2.0.0&request=GetFeature&"
                        "typeNames=global3D:lod1_global&outputFormat=application/json&"
                        "srsName=EPSG:4326&"
                        f"bbox={tx0},{ty0},{tx1},{ty1},EPSG:4326&"
                        f"viewerSession={token}"
                    )
                    try:
                        resp = self.session.get(wfs_url, headers=self.headers, verify=False, timeout=45)
                        self._requests_on_token += 1
                        if resp.status_code == 200:
                            payload = resp.json()
                            features = payload.get("features", [])
                            if features:
                                tile_gdf = gpd.GeoDataFrame.from_features(features)
                                if "id" not in tile_gdf.columns:
                                    tile_gdf["id"] = [
                                        f.get("id", f.get("properties", {}).get("ogc_fid", f"t{tile_idx}_{k}"))
                                        for k, f in enumerate(features)
                                    ]
                                tile_gdf.set_crs(epsg=4326, inplace=True)
                                all_gdfs.append(tile_gdf)
                            print(f"  [Tile {tile_idx}/{total_tiles}] Extracted {len(features)} 3D buildings.")
                            break
                        elif resp.status_code in (401, 403):
                            continue
                        else:
                            print(f"  [Tile {tile_idx}/{total_tiles}] Warning: HTTP {resp.status_code}")
                            break
                    except Exception as exc:
                        if attempt == 2:
                            print(f"  [Tile {tile_idx}/{total_tiles}] Network error: {exc}")
                        time.sleep(1.0)

        if not all_gdfs:
            raise RuntimeError("No 3D building footprints were returned from TUM WFS for the specified AOI.")

        combined = pd.concat(all_gdfs, ignore_index=True)

        # Deduplicate buildings that straddle grid tile boundaries
        if "id" in combined.columns:
            combined = combined.drop_duplicates(subset=["id"]).copy()
        elif "ogc_fid" in combined.columns:
            combined = combined.drop_duplicates(subset=["ogc_fid"]).copy()

        # Reproject to metric target CRS and clip to the exact AOI boundary
        gdf_utm = combined.to_crs(aoi.target_crs)
        gdf_utm["geometry"] = gdf_utm.geometry.apply(lambda g: make_valid(g).buffer(0) if g is not None else None)
        gdf_utm = gdf_utm[gdf_utm.geometry.notnull() & ~gdf_utm.geometry.is_empty].copy()
        gdf_utm = gdf_utm[gdf_utm.geometry.intersects(aoi.boundary_utm)].copy()
        gdf_utm = gdf_utm[gdf_utm.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

        # Compute metric gross area & filter viable buildings
        gdf_utm["gross_area_m2"] = gdf_utm.geometry.area.round(2)
        gdf_utm = gdf_utm[gdf_utm["gross_area_m2"] >= self.config.min_building_area_m2].copy()

        # Standardize 3D structural height & height variance attributes
        if "height" not in gdf_utm.columns:
            gdf_utm["height"] = self.config.default_building_height_m
        gdf_utm["building_height_m"] = (
            pd.to_numeric(gdf_utm["height"], errors="coerce")
            .fillna(self.config.default_building_height_m)
            .clip(lower=2.5)
            .round(2)
        )
        gdf_utm["height_variance"] = (
            pd.to_numeric(gdf_utm["var"], errors="coerce").fillna(0.0).round(2)
            if "var" in gdf_utm.columns
            else 0.0
        )
        gdf_utm["num_floors"] = np.maximum(1, np.round(gdf_utm["building_height_m"] / 3.2)).astype(int)
        gdf_utm["centroid_x_utm"] = gdf_utm.geometry.centroid.x.round(2)
        gdf_utm["centroid_y_utm"] = gdf_utm.geometry.centroid.y.round(2)
        gdf_utm["source_feature_id"] = (
            gdf_utm["id"].astype(str)
            if "id" in gdf_utm.columns
            else [f"tum_{i}" for i in range(len(gdf_utm))]
        )

        # Deterministic spatial sort (North-to-South, West-to-East) & immutable primary key assignment
        gdf_utm = gdf_utm.sort_values(
            by=["centroid_y_utm", "centroid_x_utm"], ascending=[False, True]
        ).reset_index(drop=True)
        gdf_utm["building_id"] = np.arange(1, len(gdf_utm) + 1, dtype=np.int64)

        keep_cols = [
            "building_id",
            "source_feature_id",
            "gross_area_m2",
            "building_height_m",
            "height_variance",
            "num_floors",
            "centroid_x_utm",
            "centroid_y_utm",
            "geometry",
        ]
        print(f"[Section 1 | Footprints] Validated {len(gdf_utm)} 3D buildings in {aoi.target_crs}.")
        return gdf_utm[keep_cols]
