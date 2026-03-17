from __future__ import annotations

import numpy as np

from river_insight import config


def compute_ndwi(green_band: np.ndarray, nir_band: np.ndarray) -> np.ndarray:
    return (green_band - nir_band) / (green_band + nir_band + 1e-6)


def compute_ndvi(nir_band: np.ndarray, red_band: np.ndarray) -> np.ndarray:
    return (nir_band - red_band) / (nir_band + red_band + 1e-6)


def compute_fvc(
    ndvi: np.ndarray,
    ndvi_soil: float,
    ndvi_veg: float,
) -> np.ndarray:
    denominator = ndvi_veg - ndvi_soil
    if denominator < 0.05:
        ndvi_soil = config.FVC_SOIL_DEFAULT
        ndvi_veg = config.FVC_VEG_DEFAULT
        denominator = ndvi_veg - ndvi_soil
    return np.clip((ndvi - ndvi_soil) / denominator, 0.0, 1.0)


def derive_fvc_series(
    ndvi_by_year: dict[int, np.ndarray],
) -> tuple[dict[int, np.ndarray], float, float]:
    values = []
    for ndvi in ndvi_by_year.values():
        valid = ndvi[np.isfinite(ndvi)]
        if valid.size:
            values.append(valid)

    if values:
        merged = np.concatenate(values)
        ndvi_soil = float(np.nanpercentile(merged, 5))
        ndvi_veg = float(np.nanpercentile(merged, 95))
    else:
        ndvi_soil = config.FVC_SOIL_DEFAULT
        ndvi_veg = config.FVC_VEG_DEFAULT

    if (ndvi_veg - ndvi_soil) < 0.05:
        ndvi_soil = config.FVC_SOIL_DEFAULT
        ndvi_veg = config.FVC_VEG_DEFAULT

    fvc_by_year = {
        year: compute_fvc(ndvi, ndvi_soil=ndvi_soil, ndvi_veg=ndvi_veg)
        for year, ndvi in ndvi_by_year.items()
    }
    return fvc_by_year, ndvi_soil, ndvi_veg
