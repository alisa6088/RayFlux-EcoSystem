"""
section1_data_gathering/footprint_harvester.py
Harvests 3D LoD1 building footprints and structural height attributes from the
TUM Global 3D WFS service for any resolved Case Study AOI, OR preserves exact
user-supplied building footprints (.shp / .geojson / .gpkg) while transferring
3D heights (`building_height_m`, `height_variance`) from spatially overlapping
TUM Global 3D LoD1 WFS buildings.
"""
from pathlib import Path
import time
from typing import List, Optional, Tuple
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

_USER_HEIGHT_CANDIDATES = (
    "building_height_m",
    "height_m",
    "height",
    "bldg_height",
    "bldg_h",
    "roof_height",
    "roof_heigh",
    "h_m",
    "h",
    "z",
    "elev",
    "elevation",
)
_USER_FLOOR_CANDIDATES = ("num_floors", "floors", "stories", "levels", "num_floo_1")


def _extract_polygon_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Repairs geometries and ensures only non-empty Polygon/MultiPolygon features remain."""
    out = gdf.copy()

    def _clean(g):
        if g is None or g.is_empty:
            return None
        fixed = make_valid(g)
        if fixed.geom_type == "GeometryCollection":
            polys = [p for p in fixed.geoms if p.geom_type in ("Polygon", "MultiPolygon") and not p.is_empty]
            if not polys:
                return None
            fixed = polys[0] if len(polys) == 1 else gpd.GeoSeries(polys).union_all()
        if fixed.geom_type not in ("Polygon", "MultiPolygon"):
            return None
        fixed = fixed.buffer(0)
        return None if fixed.is_empty else fixed

    out["geometry"] = out.geometry.apply(_clean)
    out = out[out.geometry.notnull() & ~out.geometry.is_empty].copy()
    out = out[out.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    return out


def _extract_optional_user_heights(user_gdf: gpd.GeoDataFrame) -> pd.Series:
    """Extracts an optional fallback numeric height series (in meters) from user shapefile attributes."""
    lower_map = {c.lower(): c for c in user_gdf.columns if c != "geometry"}
    for cand in _USER_HEIGHT_CANDIDATES:
        if cand in lower_map:
            vals = pd.to_numeric(user_gdf[lower_map[cand]], errors="coerce")
            vals = vals.where(vals > 0.5)
            if vals.notna().any():
                return vals.clip(lower=2.5).round(2)
    for cand in _USER_FLOOR_CANDIDATES:
        if cand in lower_map:
            floors = pd.to_numeric(user_gdf[lower_map[cand]], errors="coerce")
            floors = floors.where(floors >= 1.0)
            if floors.notna().any():
                return (floors * 3.2).clip(lower=2.5).round(2)
    return pd.Series(np.nan, index=user_gdf.index, dtype="float64")


class TUM3DFootprintHarvester:
    """Automated WFS harvester & user-footprint height-transfer engine for the TUM Global 3D LoD1 database."""

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

    def _fetch_wfs_raw_utm(self, aoi: ResolvedAOI) -> Optional[gpd.GeoDataFrame]:
        """Downloads and deduplicates raw TUM 3D LoD1 WFS buildings in `aoi.target_crs`."""
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
            return None

        combined = pd.concat(all_gdfs, ignore_index=True)

        # Deduplicate buildings that straddle grid tile boundaries
        if "id" in combined.columns:
            combined = combined.drop_duplicates(subset=["id"]).copy()
        elif "ogc_fid" in combined.columns:
            combined = combined.drop_duplicates(subset=["ogc_fid"]).copy()

        gdf_utm = combined.to_crs(aoi.target_crs)
        gdf_utm = _extract_polygon_geometries(gdf_utm)
        if gdf_utm.empty:
            return None

        if "height" not in gdf_utm.columns:
            gdf_utm["height"] = self.config.default_building_height_m
        gdf_utm["wfs_height_m"] = (
            pd.to_numeric(gdf_utm["height"], errors="coerce")
            .fillna(self.config.default_building_height_m)
            .clip(lower=2.5)
            .round(2)
        )
        gdf_utm["wfs_var"] = (
            pd.to_numeric(gdf_utm["var"], errors="coerce").fillna(0.0).round(2)
            if "var" in gdf_utm.columns
            else 0.0
        )
        gdf_utm["wfs_id"] = (
            gdf_utm["id"].astype(str)
            if "id" in gdf_utm.columns
            else [f"tum_{i}" for i in range(len(gdf_utm))]
        )
        return gdf_utm.reset_index(drop=True)

    @staticmethod
    def _finalize_schema(gdf_utm: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Applies deterministic spatial sorting, `building_id (1..N)`, and canonical S01 schema."""
        gdf_utm["gross_area_m2"] = gdf_utm.geometry.area.round(2)
        gdf_utm["num_floors"] = np.maximum(1, np.round(gdf_utm["building_height_m"] / 3.2)).astype(int)
        gdf_utm["centroid_x_utm"] = gdf_utm.geometry.centroid.x.round(2)
        gdf_utm["centroid_y_utm"] = gdf_utm.geometry.centroid.y.round(2)

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
            "height_source",
            "wfs_overlap_pct",
            "num_floors",
            "centroid_x_utm",
            "centroid_y_utm",
            "geometry",
        ]
        return gdf_utm[keep_cols]

    def resolve_user_footprints_path(self, aoi: ResolvedAOI) -> Tuple[str, Optional[Path]]:
        """Determines whether Section 1 should run in `user_footprints` or `wfs_only` mode."""
        mode = (self.config.footprint_mode or "auto").strip().lower()
        explicit_fp = Path(self.config.user_footprints_source) if self.config.user_footprints_source else None

        if mode == "wfs_only":
            return "wfs_only", None

        if explicit_fp is not None and explicit_fp.exists():
            return "user_footprints", explicit_fp

        if mode == "user_footprints":
            if aoi.source_path is not None and aoi.source_path.exists():
                return "user_footprints", aoi.source_path
            raise FileNotFoundError(
                "footprint_mode='user_footprints' requested, but no valid .shp/.geojson/.gpkg file was provided."
            )

        # Auto-detect: multi-polygon uploaded vector files (>1 feature) are building footprints
        if aoi.source_path is not None and aoi.source_path.exists() and aoi.input_feature_count > 1:
            return "user_footprints", aoi.source_path

        return "wfs_only", None

    def harvest_or_enrich_footprints(self, aoi: ResolvedAOI) -> gpd.GeoDataFrame:
        """Unified Section 1 entry point:
          - If user supplied building footprints (or auto-detected multi-polygon vector file):
            keeps exact user footprint geometries and transfers 3D heights from overlapping WFS buildings.
          - Otherwise:
            harvests both footprints and 3D heights directly from TUM Global 3D LoD1 WFS.
        """
        effective_mode, user_fp_path = self.resolve_user_footprints_path(aoi)
        if effective_mode == "user_footprints" and user_fp_path is not None:
            return self.harvest_user_footprints_with_wfs_heights(aoi, user_fp_path)
        return self.harvest_aoi_footprints(aoi)

    def harvest_user_footprints_with_wfs_heights(
        self,
        aoi: ResolvedAOI,
        user_footprints_path: Path,
    ) -> gpd.GeoDataFrame:
        """Keeps exact building footprints from the user's .shp / .geojson / .gpkg file and
        transfers `building_height_m` & `height_variance` from spatially overlapping TUM 3D WFS buildings."""
        print(f"[Section 1 | Mode] USER FOOTPRINTS + WFS HEIGHT TRANSFER ({user_footprints_path.name})")
        user_raw = gpd.read_file(user_footprints_path)
        if user_raw.empty:
            raise ValueError(f"User footprints file contains zero features: {user_footprints_path}")
        if user_raw.crs is None:
            user_raw = user_raw.set_crs(epsg=4326)

        user_utm = user_raw.to_crs(aoi.target_crs)
        user_utm = _extract_polygon_geometries(user_utm)
        # Drop only degenerate sub-1m² slivers so genuine user-digitized small buildings are preserved
        user_utm = user_utm[user_utm.geometry.area >= 1.0].reset_index(drop=True)
        if user_utm.empty:
            raise ValueError(f"No valid polygon building footprints (>= 1 m²) found in {user_footprints_path}")

        n_user = len(user_utm)
        print(f"[Section 1 | User Footprints] Loaded {n_user:,} clean user building polygons in {aoi.target_crs}.")

        # Extract optional user height attributes only as a Tier-3 fallback when WFS has no match
        user_attr_heights = _extract_optional_user_heights(user_utm)
        lower_cols = {c.lower(): c for c in user_utm.columns if c != "geometry"}
        orig_id_col = lower_cols.get("id") or lower_cols.get("fid") or lower_cols.get("fid_") or lower_cols.get("building_id")
        orig_ids = (
            user_utm[orig_id_col].astype(str).tolist()
            if orig_id_col is not None
            else [f"user_{i + 1}" for i in range(n_user)]
        )

        # Initialize result arrays
        heights = np.full(n_user, np.nan, dtype=np.float64)
        variances = np.zeros(n_user, dtype=np.float64)
        height_sources = np.full(n_user, "", dtype=object)
        overlap_pcts = np.zeros(n_user, dtype=np.float64)
        matched_wfs_ids = np.full(n_user, "", dtype=object)

        # Download TUM 3D LoD1 WFS reference buildings over the AOI for height transfer
        wfs_utm = None
        try:
            wfs_utm = self._fetch_wfs_raw_utm(aoi)
        except Exception as exc:
            print(f"[Section 1 | WFS Height Transfer] Warning: TUM WFS unavailable ({exc}); using fallback heights.")

        if wfs_utm is not None and not wfs_utm.empty:
            print(
                f"[Section 1 | WFS Height Transfer] Matching {n_user:,} user footprints against "
                f"{len(wfs_utm):,} WFS 3D reference buildings by spatial overlap..."
            )
            # Tier 1: Exact geometric polygon overlap (largest intersection area wins)
            joined = gpd.sjoin(
                user_utm[["geometry"]],
                wfs_utm[["wfs_id", "wfs_height_m", "wfs_var", "geometry"]],
                how="inner",
                predicate="intersects",
            )
            if not joined.empty:
                u_idx = joined.index.to_numpy()
                w_idx = joined["index_right"].to_numpy()
                u_geoms = user_utm.geometry.iloc[u_idx]
                w_geoms = wfs_utm.geometry.iloc[w_idx]
                inter_areas = u_geoms.intersection(w_geoms, align=False).area.to_numpy()

                ov_df = pd.DataFrame({
                    "u_idx": u_idx,
                    "wfs_id": joined["wfs_id"].to_numpy(),
                    "wfs_height_m": joined["wfs_height_m"].to_numpy(),
                    "wfs_var": joined["wfs_var"].to_numpy(),
                    "inter_area": inter_areas,
                })
                ov_df = ov_df[ov_df["inter_area"] > 0.01]
                if not ov_df.empty:
                    ov_df = ov_df.sort_values("inter_area", ascending=False).drop_duplicates(
                        subset=["u_idx"], keep="first"
                    )
                    user_areas = user_utm.geometry.area.to_numpy()
                    for row in ov_df.itertuples(index=False):
                        idx = int(row.u_idx)
                        heights[idx] = float(row.wfs_height_m)
                        variances[idx] = float(row.wfs_var)
                        height_sources[idx] = "WFS_OVERLAP"
                        matched_wfs_ids[idx] = str(row.wfs_id)
                        u_area = max(float(user_areas[idx]), 1e-6)
                        overlap_pcts[idx] = round(min(100.0, (float(row.inter_area) / u_area) * 100.0), 1)

            # Tier 2: Nearest-neighbor shift guard (within `wfs_height_nearest_max_m`, default 5.0m)
            unmatched_mask = np.isnan(heights)
            max_dist = float(getattr(self.config, "wfs_height_nearest_max_m", 5.0))
            if unmatched_mask.any() and max_dist > 0.0:
                unmatched_df = user_utm.loc[unmatched_mask, ["geometry"]]
                nearest = gpd.sjoin_nearest(
                    unmatched_df,
                    wfs_utm[["wfs_id", "wfs_height_m", "wfs_var", "geometry"]],
                    how="inner",
                    max_distance=max_dist,
                    distance_col="dist_m",
                )
                if not nearest.empty:
                    nearest = nearest.sort_values("dist_m", ascending=True)
                    nearest = nearest[~nearest.index.duplicated(keep="first")]
                    for idx, row in nearest.iterrows():
                        i = int(idx)
                        heights[i] = float(row["wfs_height_m"])
                        variances[i] = float(row["wfs_var"])
                        height_sources[i] = "WFS_NEAREST"
                        matched_wfs_ids[i] = str(row["wfs_id"])
                        overlap_pcts[i] = 0.0

        # Tier 3 & 4: User attribute fallback -> default_building_height_m
        for idx in range(n_user):
            if np.isnan(heights[idx]):
                u_h = user_attr_heights.iloc[idx]
                if pd.notna(u_h):
                    heights[idx] = float(u_h)
                    height_sources[idx] = "USER_ATTR"
                else:
                    heights[idx] = float(self.config.default_building_height_m)
                    height_sources[idx] = "DEFAULT_FALLBACK"

        out = gpd.GeoDataFrame(
            {
                "source_feature_id": [
                    f"{orig_ids[i]}|wfs:{matched_wfs_ids[i]}" if matched_wfs_ids[i] else f"{orig_ids[i]}"
                    for i in range(n_user)
                ],
                "building_height_m": np.clip(heights, 2.5, None).round(2),
                "height_variance": np.round(variances, 2),
                "height_source": height_sources,
                "wfs_overlap_pct": np.round(overlap_pcts, 1),
            },
            geometry=user_utm.geometry.values,
            crs=aoi.target_crs,
        )

        counts = pd.Series(height_sources).value_counts().to_dict()
        ov_cnt = counts.get("WFS_OVERLAP", 0)
        near_cnt = counts.get("WFS_NEAREST", 0)
        print(
            f"[Section 1 | Height Transfer Summary] Total={n_user:,} | "
            f"WFS Overlap={ov_cnt:,} ({ov_cnt / n_user * 100:.1f}%) | "
            f"WFS Nearest (<={self.config.wfs_height_nearest_max_m}m)={near_cnt:,} | "
            f"User Attr={counts.get('USER_ATTR', 0):,} | Default={counts.get('DEFAULT_FALLBACK', 0):,}"
        )
        return self._finalize_schema(out)

    def harvest_aoi_footprints(self, aoi: ResolvedAOI) -> gpd.GeoDataFrame:
        """Downloads all 3D LoD1 buildings inside the resolved AOI bounding box directly from TUM WFS,
        deduplicates edge-crossing buildings, cleans topology, and assigns `building_id`."""
        print("[Section 1 | Mode] WFS DIRECT (Harvesting footprints + heights from TUM 3D LoD1)")
        gdf_utm = self._fetch_wfs_raw_utm(aoi)
        if gdf_utm is None or gdf_utm.empty:
            raise RuntimeError("No 3D building footprints were returned from TUM WFS for the specified AOI.")

        gdf_utm = gdf_utm[gdf_utm.geometry.intersects(aoi.boundary_utm)].copy()
        gdf_utm["gross_area_m2"] = gdf_utm.geometry.area.round(2)
        gdf_utm = gdf_utm[gdf_utm["gross_area_m2"] >= self.config.min_building_area_m2].copy()
        if gdf_utm.empty:
            raise RuntimeError(
                f"Zero buildings remained inside the AOI after filtering area >= {self.config.min_building_area_m2} m²."
            )

        out = gpd.GeoDataFrame(
            {
                "source_feature_id": gdf_utm["wfs_id"].astype(str).values,
                "building_height_m": gdf_utm["wfs_height_m"].values,
                "height_variance": gdf_utm["wfs_var"].values,
                "height_source": ["WFS_DIRECT"] * len(gdf_utm),
                "wfs_overlap_pct": np.full(len(gdf_utm), 100.0, dtype=np.float64),
            },
            geometry=gdf_utm.geometry.values,
            crs=aoi.target_crs,
        )
        print(f"[Section 1 | Footprints] Validated {len(out):,} 3D buildings in {aoi.target_crs}.")
        return self._finalize_schema(out)
