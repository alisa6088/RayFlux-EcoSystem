"""
section3_solar_engine/visualizer.py
Publication-grade dark-theme visual analytics for Section 3:
  1. Rooftop Annual Solar Irradiance Heatmap overlaid on the RGB orthophoto.
  2. 7-Tier Getis-Ord Gi* Spatial Hotspot Cluster Map overlaid on the RGB orthophoto.
  3. 2-Panel PV Energy Yield Dashboard (Annual Distribution Histogram + Monthly GWh Profile).
"""
from pathlib import Path
from typing import Optional
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.patches import Patch
import numpy as np
import rasterio
from rasterio.enums import Resampling


MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _load_downsampled_ortho(ortho_tif: Optional[Path], max_dim: int = 2200):
    """Loads a downsampled RGB orthophoto array and map extent if available."""
    if ortho_tif is None or not Path(ortho_tif).exists():
        return None, None
    with rasterio.open(ortho_tif) as src:
        scale = min(1.0, max_dim / max(src.width, src.height))
        out_w = max(1, int(src.width * scale))
        out_h = max(1, int(src.height * scale))
        rgb = src.read([1, 2, 3], out_shape=(3, out_h, out_w), resampling=Resampling.bilinear)
        rgb = np.transpose(rgb, (1, 2, 0)).astype(np.uint8)
        extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
    return rgb, extent


def render_irradiance_heatmap(
    annual_rad_tif: Path,
    ortho_tif: Optional[Path],
    hotspots_gdf: gpd.GeoDataFrame,
    out_png: Path,
) -> Path:
    """Renders a 2-Panel Solar Potential Map:
      Panel 1: Per-Building Total Annual PV Electricity Yield (MWh/yr, log-scaled) — clearly shows
               how larger, high-irradiance industrial roofs generate 100x-300x more total energy.
      Panel 2: Pixel-Level Solar Irradiance Flux (kWh/m²/yr, contrast-stretched to highlight 3D shading).
    """
    out_png.parent.mkdir(parents=True, exist_ok=True)
    rgb, ortho_extent = _load_downsampled_ortho(ortho_tif, max_dim=1800)

    with rasterio.open(annual_rad_tif) as src:
        max_dim = 1800
        scale = min(1.0, max_dim / max(src.width, src.height))
        out_w = max(1, int(src.width * scale))
        out_h = max(1, int(src.height * scale))
        rad = src.read(1, out_shape=(out_h, out_w), resampling=Resampling.nearest).astype(np.float32)
        rad_extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]

    masked_rad = np.where(rad > -9000.0, rad, np.nan)
    valid_vals = masked_rad[np.isfinite(masked_rad)]
    # Stretch irradiance colorbar around the active shading zone (5th–99.5th pct) so 3D shading pops
    rad_vmin = float(np.percentile(valid_vals, 5)) if valid_vals.size > 0 else 1850.0
    rad_vmax = float(np.percentile(valid_vals, 99.5)) if valid_vals.size > 0 else 2220.0
    if rad_vmax - rad_vmin < 50.0:
        rad_vmin = max(400.0, rad_vmax - 350.0)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(22, 9.5), dpi=180)
    fig.patch.set_facecolor("#0F172A")

    # Panel 1: Per-Building Total Annual PV Yield (MWh/yr) — Log-Scaled Heatmap
    ax1.set_facecolor("#0F172A")
    if rgb is not None:
        ax1.imshow(rgb, extent=ortho_extent, origin="upper", alpha=0.55)

    valid_b = hotspots_gdf[hotspots_gdf["elec_yield_mwh_yr"] > 0].copy()
    e_min = max(10.0, float(valid_b["elec_yield_mwh_yr"].quantile(0.02))) if not valid_b.empty else 10.0
    e_max = float(valid_b["elec_yield_mwh_yr"].max()) if not valid_b.empty else 6000.0
    norm_e = LogNorm(vmin=e_min, vmax=e_max)
    valid_b.plot(
        column="elec_yield_mwh_yr",
        ax=ax1,
        cmap="inferno",
        norm=norm_e,
        edgecolor="#0F172A",
        linewidth=0.15,
        alpha=0.92,
    )
    sm1 = plt.cm.ScalarMappable(cmap="inferno", norm=norm_e)
    sm1.set_array([])
    cbar1 = fig.colorbar(sm1, ax=ax1, fraction=0.036, pad=0.02)
    cbar1.set_label("Total Annual PV Yield per Roof (MWh/yr, log scale)", color="#F8FAFC", fontsize=9.5, fontweight="bold")
    cbar1.ax.tick_params(colors="#CBD5E1", labelsize=8.5)
    ax1.set_title(
        "1. Total Annual Solar PV Yield per Building (MWh/yr)\n(Scales with Usable Roof Area × Irradiance)",
        color="#F8FAFC",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )

    # Panel 2: Pixel-Level Solar Irradiance Flux (kWh/m²/yr) — Contrast-Stretched for 3D Shading
    ax2.set_facecolor("#0F172A")
    if rgb is not None:
        ax2.imshow(rgb, extent=ortho_extent, origin="upper", alpha=0.55)

    im2 = ax2.imshow(
        masked_rad,
        extent=rad_extent,
        origin="upper",
        cmap="plasma",
        vmin=rad_vmin,
        vmax=rad_vmax,
        alpha=0.94,
    )
    cbar2 = fig.colorbar(im2, ax=ax2, fraction=0.036, pad=0.02)
    cbar2.set_label("Specific Solar Irradiance Flux (kWh/m²/yr)", color="#F8FAFC", fontsize=9.5, fontweight="bold")
    cbar2.ax.tick_params(colors="#CBD5E1", labelsize=8.5)
    ax2.set_title(
        f"2. Pixel-Level Irradiance Flux & 3D Shading (kWh/m²/yr)\n(Contrast-Stretched {rad_vmin:,.0f}–{rad_vmax:,.0f} kWh/m²/yr)",
        color="#F8FAFC",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )

    for ax in (ax1, ax2):
        if ortho_extent is not None:
            ax.set_xlim(ortho_extent[0], ortho_extent[1])
            ax.set_ylim(ortho_extent[2], ortho_extent[3])
        ax.set_xlabel("Easting (m)", color="#CBD5E1", fontsize=9)
        ax.set_ylabel("Northing (m)", color="#CBD5E1", fontsize=9)
        ax.tick_params(colors="#94A3B8", labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#334155")

    mean_rad = float(hotspots_gdf["mean_kwh_m2_yr"].mean()) if not hotspots_gdf.empty else 0.0
    total_gwh = float(hotspots_gdf["elec_yield_mwh_yr"].sum()) / 1000.0 if not hotspots_gdf.empty else 0.0
    total_mwp = float(hotspots_gdf["installed_capacity_kwp"].sum()) / 1000.0 if not hotspots_gdf.empty else 0.0

    fig.suptitle(
        f"RayFlux Section 3: Rooftop Solar Potential & 3D Irradiance Map  |  "
        f"Buildings: {len(hotspots_gdf):,}  |  Mean Flux: {mean_rad:,.1f} kWh/m²/yr  |  "
        f"Capacity: {total_mwp:,.1f} MWp  |  Annual PV Yield: {total_gwh:,.1f} GWh/yr",
        color="#F8FAFC",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out_png, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_png


def render_hotspots_cluster_map(
    hotspots_gdf: gpd.GeoDataFrame,
    ortho_tif: Optional[Path],
    out_png: Path,
) -> Path:
    """Renders the 7-tier Getis-Ord Gi* Solar PV Spatial Hotspot Cluster Map."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    rgb, ortho_extent = _load_downsampled_ortho(ortho_tif)

    color_map = {
        "Hot Spot (99%)": "#DC2626",
        "Hot Spot (95%)": "#F97316",
        "Hot Spot (90%)": "#FACC15",
        "Not Significant": "#94A3B8",
        "Cold Spot (90%)": "#7DD3FC",
        "Cold Spot (95%)": "#3B82F6",
        "Cold Spot (99%)": "#1D4ED8",
    }

    fig, ax = plt.subplots(figsize=(16, 11), dpi=180)
    fig.patch.set_facecolor("#0F172A")
    ax.set_facecolor("#0F172A")

    if rgb is not None:
        ax.imshow(rgb, extent=ortho_extent, origin="upper", alpha=0.60)

    legend_handles = []
    for cls_name, hex_col in color_map.items():
        sub = hotspots_gdf[hotspots_gdf["gi_cluster_class"] == cls_name]
        cnt = len(sub)
        alpha = 0.88 if cls_name != "Not Significant" else 0.45
        if cnt > 0:
            sub.plot(ax=ax, facecolor=hex_col, edgecolor="#0F172A", linewidth=0.18, alpha=alpha)
        legend_handles.append(
            Patch(facecolor=hex_col, edgecolor="#0F172A", alpha=alpha, label=f"{cls_name} ({cnt:,})")
        )

    hot_total = int(hotspots_gdf["gi_cluster_class"].str.startswith("Hot Spot").sum())
    cold_total = int(hotspots_gdf["gi_cluster_class"].str.startswith("Cold Spot").sum())
    total_gwh = float(hotspots_gdf["elec_yield_mwh_yr"].sum()) / 1000.0

    ax.set_title(
        f"RayFlux Section 3: Getis-Ord Gi* Solar PV Spatial Hotspot Analysis (Gaussian Kernel k=10, star=True)\n"
        f"Buildings: {len(hotspots_gdf):,}  |  Hot Spots: {hot_total:,}  |  Cold Spots: {cold_total:,}  |  "
        f"Total Annual PV Yield: {total_gwh:,.1f} GWh/yr",
        color="#F8FAFC",
        fontsize=12,
        fontweight="bold",
        pad=14,
    )
    ax.legend(
        handles=legend_handles,
        title="Gi* Significance Tier",
        title_fontsize=10,
        fontsize=9,
        loc="lower right",
        frameon=True,
        facecolor="#1E293B",
        edgecolor="#475569",
        labelcolor="white",
    )
    leg = ax.get_legend()
    if leg is not None:
        leg.get_title().set_color("#F8FAFC")

    ax.set_xlabel("Easting (m)", color="#CBD5E1", fontsize=9)
    ax.set_ylabel("Northing (m)", color="#CBD5E1", fontsize=9)
    ax.tick_params(colors="#94A3B8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")

    plt.tight_layout()
    fig.savefig(out_png, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_png


def render_energy_distribution(
    hotspots_gdf: gpd.GeoDataFrame,
    out_png: Path,
) -> Path:
    """Renders a 2-panel PV Energy Dashboard: Annual Yield Histogram + Monthly Citywide Generation Profile."""
    out_png.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6.2), dpi=180)
    fig.patch.set_facecolor("#0F172A")

    # Panel 1: Log-spaced / capped Annual PV Yield Histogram
    vals = hotspots_gdf["elec_yield_mwh_yr"].to_numpy(dtype=np.float64)
    p98 = float(np.percentile(vals, 98)) if vals.size > 0 else 100.0
    clipped = np.clip(vals, 0, p98)

    ax1.set_facecolor("#1E293B")
    ax1.hist(clipped, bins=45, color="#F59E0B", edgecolor="#0F172A", alpha=0.88)
    mean_v = float(vals.mean()) if vals.size > 0 else 0.0
    med_v = float(np.median(vals)) if vals.size > 0 else 0.0
    ax1.axvline(mean_v, color="#38BDF8", linestyle="--", linewidth=1.8, label=f"Mean: {mean_v:.1f} MWh/yr")
    ax1.axvline(med_v, color="#10B981", linestyle="-.", linewidth=1.8, label=f"Median: {med_v:.1f} MWh/yr")
    ax1.set_title("Per-Building Annual PV Yield Distribution (98th-Pct Clip)", color="#F8FAFC", fontsize=11, fontweight="bold", pad=10)
    ax1.set_xlabel("Annual Electricity Potential (MWh/yr)", color="#CBD5E1", fontsize=10)
    ax1.set_ylabel("Number of Buildings", color="#CBD5E1", fontsize=10)
    ax1.tick_params(colors="#94A3B8", labelsize=9)
    ax1.grid(axis="y", color="#334155", alpha=0.5)
    ax1.legend(facecolor="#0F172A", edgecolor="#475569", labelcolor="white", fontsize=9)
    for spine in ax1.spines.values():
        spine.set_edgecolor("#334155")

    # Panel 2: Monthly Citywide PV Electricity Yield (GWh/month)
    monthly_gwh = [float(hotspots_gdf[f"elec_mwh_m{m:02d}"].sum()) / 1000.0 for m in range(1, 13)]
    ax2.set_facecolor("#1E293B")
    bars = ax2.bar(MONTH_LABELS, monthly_gwh, color="#10B981", edgecolor="#064E3B", alpha=0.90)
    for bar, val in zip(bars, monthly_gwh):
        ax2.text(
            bar.get_x() + bar.get_width() / 2.0,
            val + max(monthly_gwh) * 0.015,
            f"{val:.1f}",
            ha="center",
            va="bottom",
            color="#E2E8F0",
            fontsize=8,
            fontweight="bold",
        )
    ax2.set_ylim(0, max(monthly_gwh) * 1.15 if max(monthly_gwh) > 0 else 1.0)
    ax2.set_title(
        f"Monthly Citywide PV Electricity Generation (Total: {sum(monthly_gwh):,.1f} GWh/yr)",
        color="#F8FAFC",
        fontsize=11,
        fontweight="bold",
        pad=10,
    )
    ax2.set_xlabel("Month", color="#CBD5E1", fontsize=10)
    ax2.set_ylabel("PV Electricity Yield (GWh/month)", color="#CBD5E1", fontsize=10)
    ax2.tick_params(colors="#94A3B8", labelsize=9)
    ax2.grid(axis="y", color="#334155", alpha=0.5)
    for spine in ax2.spines.values():
        spine.set_edgecolor("#334155")

    fig.suptitle(
        f"RayFlux Section 3: Rooftop Solar PV Energy Potential Dashboard ({len(hotspots_gdf):,} Buildings)",
        color="#F8FAFC",
        fontsize=13,
        fontweight="bold",
        y=0.99,
    )
    plt.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(out_png, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_png
