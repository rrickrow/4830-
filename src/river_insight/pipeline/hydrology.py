from __future__ import annotations

import numpy as np


_OFFSETS = [
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
]


def compute_flow_accumulation(dem: np.ndarray) -> np.ndarray:
    dem = np.asarray(dem, dtype=float)
    valid = np.isfinite(dem)
    rows, cols = dem.shape
    downstream = np.full((rows, cols, 2), -1, dtype=int)

    for row in range(rows):
        for col in range(cols):
            if not valid[row, col]:
                continue
            current = dem[row, col]
            best_value = current
            best_target: tuple[int, int] | None = None
            for dr, dc in _OFFSETS:
                nr = row + dr
                nc = col + dc
                if nr < 0 or nc < 0 or nr >= rows or nc >= cols or not valid[nr, nc]:
                    continue
                neighbor = dem[nr, nc]
                if neighbor < best_value:
                    best_value = neighbor
                    best_target = (nr, nc)
            if best_target is not None:
                downstream[row, col] = best_target

    accumulation = np.where(valid, 1.0, np.nan)
    ordered = np.dstack(np.indices(dem.shape)).reshape(-1, 2)
    ordered = ordered[valid.ravel()]
    ordered = ordered[np.argsort(dem[valid])[::-1]]

    for row, col in ordered:
        target_row, target_col = downstream[row, col]
        if target_row >= 0:
            accumulation[target_row, target_col] += accumulation[row, col]

    return accumulation


def compute_runoff_potential_index(dem: np.ndarray, resolution_m: float) -> float:
    if not np.isfinite(dem).any():
        return float("nan")

    grad_y, grad_x = np.gradient(dem, resolution_m, resolution_m)
    slope = np.sqrt(np.square(grad_x) + np.square(grad_y))
    accumulation = compute_flow_accumulation(dem)

    slope_valid = slope[np.isfinite(slope)]
    acc_valid = accumulation[np.isfinite(accumulation)]
    if slope_valid.size == 0 or acc_valid.size == 0:
        return float("nan")

    slope_norm = slope / (np.nanmax(slope_valid) + 1e-6)
    acc_norm = np.log1p(accumulation) / (np.log1p(np.nanmax(acc_valid)) + 1e-6)
    runoff = slope_norm * acc_norm
    return float(np.nanmean(runoff))
