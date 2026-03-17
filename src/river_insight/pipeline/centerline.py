from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
from scipy.ndimage import distance_transform_edt
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point
from skimage.morphology import skeletonize

from river_insight import config


_NEIGHBORS = [
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
]


@dataclass(slots=True)
class CenterlineExtractionResult:
    centerline_gdf: gpd.GeoDataFrame
    nodes_gdf: gpd.GeoDataFrame
    point_coords_xy: np.ndarray
    centerline_length_km: float
    mean_width_m: float
    point_count: int


def extract_centerline_features(
    mask: np.ndarray,
    bounds: tuple[float, float, float, float],
    resolution_m: float,
    year: int,
) -> CenterlineExtractionResult:
    skeleton = skeletonize(mask.astype(bool))
    coords = np.argwhere(skeleton)
    if coords.size == 0:
        empty_lines = gpd.GeoDataFrame(
            columns=["year", "geometry"], geometry="geometry", crs=config.MAP_CRS
        )
        empty_nodes = gpd.GeoDataFrame(
            columns=["year", "node_type", "degree", "geometry"],
            geometry="geometry",
            crs=config.MAP_CRS,
        )
        return CenterlineExtractionResult(
            centerline_gdf=empty_lines,
            nodes_gdf=empty_nodes,
            point_coords_xy=np.empty((0, 2), dtype=float),
            centerline_length_km=0.0,
            mean_width_m=float("nan"),
            point_count=0,
        )

    coord_set = {tuple(value) for value in coords.tolist()}
    segment_rows: list[dict[str, object]] = []
    node_rows: list[dict[str, object]] = []
    seen_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    xy_points: list[tuple[float, float]] = []

    for row, col in coord_set:
        xy = pixel_to_xy(row, col, bounds, resolution_m)
        xy_points.append(xy)
        degree = 0
        for dr, dc in _NEIGHBORS:
            neighbor = (row + dr, col + dc)
            if neighbor in coord_set:
                degree += 1
                edge = tuple(sorted(((row, col), neighbor)))
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                segment_rows.append(
                    {
                        "year": year,
                        "geometry": LineString([xy, pixel_to_xy(neighbor[0], neighbor[1], bounds, resolution_m)]),
                    }
                )

        if degree >= 3 or degree == 1:
            node_rows.append(
                {
                    "year": year,
                    "node_type": "junction" if degree >= 3 else "endpoint",
                    "degree": degree,
                    "geometry": Point(xy),
                }
            )

    centerline_gdf = gpd.GeoDataFrame(segment_rows, geometry="geometry", crs=config.MAP_CRS)
    nodes_gdf = gpd.GeoDataFrame(node_rows, geometry="geometry", crs=config.MAP_CRS)

    if centerline_gdf.empty:
        centerline_length_km = 0.0
    else:
        centerline_length_km = float(centerline_gdf.length.sum()) / 1000.0

    distance_map = distance_transform_edt(mask.astype(bool)) * resolution_m
    widths = distance_map[skeleton]
    mean_width_m = float(np.nanmean(widths) * 2.0) if widths.size else float("nan")

    return CenterlineExtractionResult(
        centerline_gdf=centerline_gdf,
        nodes_gdf=nodes_gdf,
        point_coords_xy=np.asarray(xy_points, dtype=float),
        centerline_length_km=centerline_length_km,
        mean_width_m=mean_width_m,
        point_count=len(xy_points),
    )


def compute_migration_metrics(
    previous_points: np.ndarray,
    current_points: np.ndarray,
) -> tuple[float | None, float | None]:
    if previous_points.size == 0 or current_points.size == 0:
        return None, None

    tree = cKDTree(previous_points)
    distances, _ = tree.query(current_points, k=1)
    if distances.size == 0:
        return None, None

    return float(np.mean(distances)), float(np.percentile(distances, 95))


def compute_slope_mean(dem: np.ndarray, resolution_m: float) -> float:
    grad_y, grad_x = np.gradient(dem, resolution_m, resolution_m)
    slope = np.sqrt(np.square(grad_x) + np.square(grad_y))
    return float(np.nanmean(slope))


def pixel_to_xy(
    row: int,
    col: int,
    bounds: tuple[float, float, float, float],
    resolution_m: float,
) -> tuple[float, float]:
    x_min, y_min, _, y_max = bounds
    x = x_min + ((col + 0.5) * resolution_m)
    y = y_max - ((row + 0.5) * resolution_m)
    return (x, y)
