from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.ndimage import distance_transform_edt


def compute_buffer_stats(
    year: int,
    ndvi: np.ndarray,
    fvc: np.ndarray,
    water_mask: np.ndarray,
    resolution_m: float,
    buffer_distances_m: tuple[int, ...],
) -> pd.DataFrame:
    distances = distance_transform_edt(~water_mask.astype(bool)) * resolution_m
    rows: list[dict[str, float | int | str]] = []
    lower = 0

    for upper in buffer_distances_m:
        zone_mask = (~water_mask) & (distances > lower) & (distances <= upper)
        if zone_mask.any():
            ndvi_mean = float(np.nanmean(np.where(zone_mask, ndvi, np.nan)))
            fvc_mean = float(np.nanmean(np.where(zone_mask, fvc, np.nan)))
        else:
            ndvi_mean = float("nan")
            fvc_mean = float("nan")

        rows.append(
            {
                "year": year,
                "buffer_label": f"{lower}-{upper}m",
                "buffer_min_m": lower,
                "buffer_max_m": upper,
                "ndvi_mean": ndvi_mean,
                "fvc_mean": fvc_mean,
            }
        )
        lower = upper

    return pd.DataFrame(rows)


def add_fvc_deltas(fvc_stats: pd.DataFrame) -> pd.DataFrame:
    if fvc_stats.empty:
        result = fvc_stats.copy()
        result["delta_fvc"] = []
        return result

    result = fvc_stats.sort_values(["buffer_min_m", "year"]).copy()
    result["delta_fvc"] = result.groupby("buffer_label")["fvc_mean"].diff()
    return result
