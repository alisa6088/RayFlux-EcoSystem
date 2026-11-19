"""
section2_object_detection/visualizer.py
Publication-grade visual QA for Section 2:
  1. 4-panel per-building diagnostic cards (RGB, GLCM/Gabor features, Obstacles vs Shadows, Net Usable Roof).
  2. Full-scene rooftop object detection overview map overlaid on the orthophoto.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, PathPatch
from matplotlib.path import Path as MplPath
import numpy as np
import rasterio
from rasterio.enums import Resampling
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient


def _plot_shapely_geom(
    ax: plt.Axes,
    geom: Any,
    win_transform: Any,
    facecolor: str = "none",
    edgecolor: str = "#00E5FF",
    linewidth: float = 1.5,
    alpha: float = 1.0,
    hole_edgecolor: Optional[str] = None,
) -> None:
    """Plots a Shapely Polygon/MultiPolygon in pixel coordinates with TRUE transparent compound-path holes."""
    if geom is None or geom.is_empty:
        return
    inv = ~win_transform

    def _ring_to_path(ring_coords) -> MplPath:
        pts = [inv * (x, y) for x, y in ring_coords]
        codes = [MplPath.MOVETO] + [MplPath.LINETO] * (len(pts) - 2) + [MplPath.CLOSEPOLY]
        return MplPath(pts, codes)

    polys = [geom] if isinstance(geom, Polygon) else (list(geom.geoms) if isinstance(geom, MultiPolygon) else [])
    for poly in polys:
        if poly.is_empty:
            continue
        # Orient exterior CCW (+1) and interiors CW (-1) so matplotlib non-zero winding punches true holes
        poly_ord = orient(poly, sign=1.0)
        paths = [_ring_to_path(poly_ord.exterior.coords)]
        for interior in poly_ord.interiors:
            paths.append(_ring_to_path(interior.coords))

        compound = MplPath.make_compound_path(*paths)
        patch = PathPatch(
            compound,
            facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            alpha=alpha,
        )
        ax.add_patch(patch)

        if hole_edgecolor is not None:
            for interior in poly_ord.interiors:
                pts = [inv * (x, y) for x, y in interior.coords]
                xs, ys = zip(*pts)
                ax.plot(xs, ys, color=hole_edgecolor, linewidth=max(0.7, linewidth * 0.7), alpha=0.95)


def render_roof_diagnostic_card(
    building_id: int,
    rgb_img: np.ndarray,
    win_transform: Any,
    gross_geom: Any,
    net_geom: Any,
    det_res: Dict[str, Any],
    metrics: Dict[str, Any],
    out_png: Path,
) -> Path:
    """Renders a 4-panel V3 CV diagnostic card for a single building."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    h, w = rgb_img.shape[:2]

    fig, axes = plt.subplots(1, 4, figsize=(18, 4.8), dpi=160)
    fig.patch.set_facecolor("#0F172A")

    # Panel 1: RGB Crop + Gross Roof Boundary
    ax0 = axes[0]
    ax0.imshow(rgb_img)
    _plot_shapely_geom(ax0, gross_geom, win_transform, facecolor="none", edgecolor="#38BDF8", linewidth=1.8)
    ax0.set_title("1. RGB Ortho & Gross Footprint", color="white", fontsize=10, fontweight="bold", pad=8)
    ax0.axis("off")

    # Panel 2: GLCM Contrast Heatmap (inside roof mask)
    ax1 = axes[1]
    glcm_con = det_res["glcm_contrast"]
    roof_mask = det_res["roof_mask"]
    masked_glcm = np.where(roof_mask > 0, glcm_con, np.nan)
    ax1.imshow(rgb_img, alpha=0.25)
    vmax = max(float(np.nanpercentile(masked_glcm, 98)) if np.any(roof_mask > 0) else 40.0, 20.0)
    im = ax1.imshow(masked_glcm, cmap="inferno", vmin=0.0, vmax=vmax, alpha=0.92)
    cbar = plt.colorbar(im, ax=ax1, fraction=0.046, pad=0.02)
    cbar.ax.tick_params(colors="white", labelsize=7)
    ax1.set_title("2. 4-Dir GLCM Texture Contrast", color="white", fontsize=10, fontweight="bold", pad=8)
    ax1.axis("off")

    # Panel 3: Disambiguated Physical Obstacles (Yellow) vs Cast Shadows (Blue)
    # Using high-contrast Yellow for obstacles prevents visual confusion on red-painted roofs.
    ax2 = axes[2]
    overlay = rgb_img.astype(np.float32).copy()
    phys_mask = det_res["physical_objects_mask"] > 0
    shd_mask = det_res["shadows_mask"] > 0
    overlay[shd_mask] = overlay[shd_mask] * 0.35 + np.array([37, 99, 235], dtype=np.float32) * 0.65
    overlay[phys_mask] = overlay[phys_mask] * 0.20 + np.array([250, 204, 21], dtype=np.float32) * 0.80
    ax2.imshow(np.clip(overlay, 0, 255).astype(np.uint8))
    _plot_shapely_geom(ax2, gross_geom, win_transform, facecolor="none", edgecolor="#E2E8F0", linewidth=1.0, alpha=0.7)
    ax2.set_title("3. Obstacles (Yellow) vs Shadows (Blue)", color="white", fontsize=10, fontweight="bold", pad=8)
    ax2.axis("off")

    # Panel 4: Net Usable Roof Polygon (Green with true transparent obstacle holes outlined in red)
    ax3 = axes[3]
    ax3.imshow(rgb_img)
    _plot_shapely_geom(ax3, gross_geom, win_transform, facecolor="none", edgecolor="#94A3B8", linewidth=1.0, alpha=0.7)
    _plot_shapely_geom(
        ax3,
        net_geom,
        win_transform,
        facecolor="#10B981",
        edgecolor="#34D399",
        linewidth=0.9,
        alpha=0.45,
        hole_edgecolor="#EF4444",
    )
    ax3.set_title("4. Net Usable Rooftop (PV-Ready)", color="white", fontsize=10, fontweight="bold", pad=8)
    ax3.axis("off")

    suptitle = (
        f"RayFlux Section 2 Diagnostic | Building #{building_id:04d}  |  "
        f"Gross: {metrics['orig_area']:.1f} m²  |  Obstacles: {metrics['obj_area']:.1f} m² ({metrics['obj_cnt']} objs)  |  "
        f"Shadows: {metrics['shd_area']:.1f} m²  |  Net Usable: {metrics['net_area']:.1f} m² ({metrics['usable_pct']:.1f}% - {metrics['status']})"
    )
    fig.suptitle(suptitle, color="#F8FAFC", fontsize=10.5, fontweight="bold", y=0.98)

    plt.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(out_png, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_png


def render_scene_detection_map(
    ortho_tif_path: Path,
    usable_gdf: gpd.GeoDataFrame,
    obstacles_gdf: gpd.GeoDataFrame,
    shadows_gdf: gpd.GeoDataFrame,
    out_png: Path,
) -> Path:
    """Renders the full-scene Section 2 overview map overlaid on a downsampled RGB orthophoto."""
    out_png.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(ortho_tif_path) as src:
        max_dim = 2200
        scale = min(1.0, max_dim / max(src.width, src.height))
        out_w = max(1, int(src.width * scale))
        out_h = max(1, int(src.height * scale))
        rgb = src.read(
            [1, 2, 3],
            out_shape=(3, out_h, out_w),
            resampling=Resampling.bilinear,
        )
        rgb = np.transpose(rgb, (1, 2, 0)).astype(np.uint8)
        extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]

    fig, ax = plt.subplots(figsize=(16, 11), dpi=180)
    fig.patch.set_facecolor("#0F172A")
    ax.set_facecolor("#0F172A")

    ax.imshow(rgb, extent=extent, origin="upper", alpha=0.88)

    status_colors = {
        "EXCELLENT": "#10B981",
        "GOOD": "#84CC16",
        "MODERATE": "#F59E0B",
        "LIMITED": "#EF4444",
    }

    if not usable_gdf.empty:
        valid_usable = usable_gdf[~usable_gdf.geometry.is_empty & usable_gdf.geometry.notnull()]
        for status, color in status_colors.items():
            sub = valid_usable[valid_usable["suitability_status"] == status]
            if not sub.empty:
                sub.plot(ax=ax, facecolor=color, edgecolor=color, linewidth=0.35, alpha=0.50)

    if shadows_gdf is not None and not shadows_gdf.empty:
        shadows_gdf.plot(ax=ax, facecolor="#2563EB", edgecolor="none", alpha=0.45)

    if obstacles_gdf is not None and not obstacles_gdf.empty:
        obstacles_gdf.plot(ax=ax, facecolor="#DC2626", edgecolor="#FCA5A5", linewidth=0.25, alpha=0.85)

    total_bldgs = len(usable_gdf)
    total_gross = float(usable_gdf["gross_area_m2"].sum()) if total_bldgs else 0.0
    total_usable = float(usable_gdf["usable_area_m2"].sum()) if total_bldgs else 0.0
    total_obs_area = float(usable_gdf["obstacle_area_m2"].sum()) if total_bldgs else 0.0
    total_obs_cnt = len(obstacles_gdf) if obstacles_gdf is not None else 0
    total_shd_cnt = len(shadows_gdf) if shadows_gdf is not None else 0
    usable_ratio = (total_usable / total_gross * 100.0) if total_gross > 0 else 0.0

    ax.set_title(
        f"RayFlux Section 2: Multi-Modal Rooftop Object Detection & Net Usable Area Map\n"
        f"Buildings: {total_bldgs:,}  |  Gross Roof: {total_gross/1e4:.2f} ha  |  "
        f"Net Usable: {total_usable/1e4:.2f} ha ({usable_ratio:.1f}%)  |  "
        f"Obstacles: {total_obs_cnt:,} ({total_obs_area/1e4:.2f} ha)  |  Cast Shadows: {total_shd_cnt:,}",
        color="#F8FAFC",
        fontsize=12,
        fontweight="bold",
        pad=14,
    )

    legend_handles = [
        Patch(facecolor="#10B981", edgecolor="#10B981", alpha=0.65, label="Usable Roof: EXCELLENT (≥60%)"),
        Patch(facecolor="#84CC16", edgecolor="#84CC16", alpha=0.65, label="Usable Roof: GOOD (40–60%)"),
        Patch(facecolor="#F59E0B", edgecolor="#F59E0B", alpha=0.65, label="Usable Roof: MODERATE (20–40%)"),
        Patch(facecolor="#EF4444", edgecolor="#EF4444", alpha=0.65, label="Usable Roof: LIMITED (<20%)"),
        Patch(facecolor="#DC2626", edgecolor="#FCA5A5", alpha=0.90, label="Physical Obstacles (Subtracted)"),
        Patch(facecolor="#2563EB", edgecolor="none", alpha=0.55, label="Cast Shadows (Retained as Usable)"),
    ]
    leg = ax.legend(
        handles=legend_handles,
        loc="lower right",
        frameon=True,
        facecolor="#1E293B",
        edgecolor="#475569",
        fontsize=9,
        labelcolor="white",
    )

    ax.set_xlabel("Easting (m)", color="#CBD5E1", fontsize=9)
    ax.set_ylabel("Northing (m)", color="#CBD5E1", fontsize=9)
    ax.tick_params(colors="#94A3B8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")

    plt.tight_layout()
    fig.savefig(out_png, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_png
