from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage.filters import threshold_otsu
from skimage.measure import label
from skimage.morphology import closing, opening

from river_insight import config


@dataclass(slots=True)
class WaterExtractionResult:
    mask: np.ndarray
    threshold: float
    used_fallback: bool


def extract_water_mask(
    ndwi: np.ndarray,
    min_connected_pixels: int = config.MIN_CONNECTED_PIXELS,
) -> WaterExtractionResult:
    valid = ndwi[np.isfinite(ndwi)]
    used_fallback = False

    if valid.size == 0:
        threshold = config.OTSU_FALLBACK_THRESHOLD
        used_fallback = True
    else:
        try:
            threshold = float(threshold_otsu(valid))
        except ValueError:
            threshold = config.OTSU_FALLBACK_THRESHOLD
            used_fallback = True

    mask = ndwi > threshold
    if mask.all() or (~mask).all():
        threshold = config.OTSU_FALLBACK_THRESHOLD
        used_fallback = True
        mask = ndwi > threshold

    kernel = np.ones((3, 3), dtype=bool)
    cleaned = opening(mask, footprint=kernel)
    cleaned = closing(cleaned, footprint=kernel)
    filtered = filter_connected_components(cleaned, min_connected_pixels=min_connected_pixels)

    if filtered.any():
        mask = filtered
    else:
        mask = cleaned

    return WaterExtractionResult(mask=mask.astype(bool), threshold=threshold, used_fallback=used_fallback)


def filter_connected_components(mask: np.ndarray, min_connected_pixels: int) -> np.ndarray:
    labeled = label(mask.astype(bool), connectivity=2)
    if labeled.max() == 0:
        return np.zeros_like(mask, dtype=bool)

    counts = np.bincount(labeled.ravel())
    keep = counts >= min_connected_pixels
    keep[0] = False
    return keep[labeled]


def compute_water_area_km2(mask: np.ndarray, resolution_m: float = config.RESOLUTION_M) -> float:
    area_m2 = float(mask.sum()) * (resolution_m * resolution_m)
    return area_m2 / 1_000_000.0
