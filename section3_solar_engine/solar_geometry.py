"""
section3_solar_engine/solar_geometry.py
Step 3.1 — Solar Position & Clear-Sky Irradiance Time Grid.
Upgraded from legacy v01/1.1_solar_geometry.py:
  - Extracts AOI center latitude/longitude directly from Section 1 Synthetic DSM.
  - Preserves physical site elevation above sea level (does not overwrite with 0m relative DSM ground).
  - Uses complete 24-hour UTC sample days so monthly sample counts are never split across UTC midnight.
  - Computes true pvlib.clearsky.haurwitz(apparent_zenith) clear-sky GHI (W/m²).
"""
from pathlib import Path
from typing import Dict, Tuple
import numpy as np
import pandas as pd
import pvlib
import rasterio
from pyproj import Transformer

from section3_solar_engine.solar_config import SolarParameters


SOLAR_CONSTANT = 1361.0
ATMOSPHERIC_FACTOR = 0.75


def extract_dsm_center_latlon(dsm_path: Path, default_altitude_m: float) -> Tuple[float, float, float]:
    """Extracts center (lat, lon) in WGS84 and physical altitude (m) from the DSM raster."""
    with rasterio.open(dsm_path) as src:
        col = src.width // 2
        row = src.height // 2
        x, y = src.xy(row, col)
        transformer = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(x, y)

        # Only override altitude_m if DSM carries absolute terrain elevation (> 50 m median),
        # never overwrite with 0.0 m from a relative building-only Synthetic DSM.
        sample = src.read(1, masked=True)
        valid = sample[~sample.mask] if np.ma.is_masked(sample) else sample[np.isfinite(sample)]
        median_z = float(np.median(valid)) if valid.size > 0 else 0.0
        altitude_m = median_z if median_z > 50.0 else float(default_altitude_m)

    return float(lat), float(lon), altitude_m


def generate_solar_geometry(
    dsm_path: Path,
    out_csv_path: Path,
    params: SolarParameters,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Generates the annual solar geometry and clear-sky GHI lookup table."""
    sg = params.solar_geometry
    n_dirs = params.horizon.n_directions

    lat, lon, altitude_m = extract_dsm_center_latlon(dsm_path, sg.altitude_m)

    freq_min = max(1, int(round(sg.hour_interval * 60)))
    times_full = pd.date_range(
        start=f"{sg.year}-01-01 00:00",
        end=f"{sg.year}-12-31 23:59",
        freq=f"{freq_min}min",
        tz=sg.timezone,
    )

    # Keep complete 24-hour days where (day_of_year - 1) % day_interval == 0
    # Guaranteeing every month 1..12 has at least 2 complete evenly spaced sample days.
    day_of_year = times_full.dayofyear
    mask_days = ((day_of_year - 1) % sg.day_interval) == 0
    times = times_full[mask_days]

    solpos = pvlib.solarposition.get_solarposition(times, lat, lon, altitude=altitude_m)

    df = pd.DataFrame(index=times)
    df["zenith"] = solpos["zenith"].astype(np.float64)
    df["apparent_zenith"] = solpos["apparent_zenith"].astype(np.float64)
    df["azimuth"] = solpos["azimuth"].astype(np.float64)
    df["sun_altitude"] = 90.0 - df["apparent_zenith"]
    df["day_of_year"] = times.dayofyear
    df["month"] = times.month
    df["dir_idx"] = (np.round(df["azimuth"] / (360.0 / n_dirs)).astype(int)) % n_dirs

    if sg.clear_sky_model.lower() == "haurwitz":
        cs = pvlib.clearsky.haurwitz(df["apparent_zenith"])
        ghi = cs["ghi"].fillna(0.0).clip(lower=0.0).to_numpy(dtype=np.float64)
    else:
        cos_z = np.clip(np.cos(np.radians(df["apparent_zenith"])), 0.0, None)
        ghi = SOLAR_CONSTANT * ATMOSPHERIC_FACTOR * cos_z

    df["ghi_clear"] = ghi * float(sg.atmospheric_clearness_kt)
    df.loc[df["sun_altitude"] <= 0.0, "ghi_clear"] = 0.0

    out_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv_path, index_label="datetime")

    # Quick theoretical unshaded horizontal annual GHI check (SVF = 1.0, no horizon shading)
    is_leap = (sg.year % 4 == 0 and sg.year % 100 != 0) or (sg.year % 400 == 0)
    days_in_month = [31, 29 if is_leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    unshaded_annual_kwhm2 = 0.0
    for m in range(1, 13):
        m_df = df[df["month"] == m]
        n_days = int(m_df["day_of_year"].nunique())
        if n_days > 0:
            unshaded_annual_kwhm2 += float(m_df["ghi_clear"].sum()) * sg.hour_interval * (days_in_month[m - 1] / n_days) * 1e-3

    meta = {
        "center_lat": round(lat, 6),
        "center_lon": round(lon, 6),
        "altitude_m": round(altitude_m, 2),
        "total_timesteps": int(len(df)),
        "daytime_timesteps": int((df["sun_altitude"] > 0.0).sum()),
        "sample_days": int(df["day_of_year"].nunique()),
        "unshaded_annual_ghi_kwhm2": round(unshaded_annual_kwhm2, 2),
    }
    return df, meta
