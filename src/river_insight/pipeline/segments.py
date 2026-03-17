from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring

from river_insight import config
from river_insight.domain.models import SegmentResponseRecord
from river_insight.pipeline.centerline import pixel_to_xy


def compute_segment_metrics(
    year: int,
    centerlines_gdf: gpd.GeoDataFrame,
    bounds: tuple[float, float, float, float],
    resolution_m: float,
    water_mask: np.ndarray,
    fvc: np.ndarray,
    precipitation: np.ndarray,
    land_use_intensity: np.ndarray,
    segment_length_m: float,
    stat_buffer_m: float,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    merged_lines = _merged_lines(centerlines_gdf)
    if not merged_lines:
        return gpd.GeoDataFrame(
            {
                "year": [],
                "line_id": [],
                "segment_index": [],
                "segment_length_m": [],
                "mean_width_m": [],
                "fvc_mean": [],
                "precipitation_mean": [],
                "land_use_intensity_mean": [],
                "midpoint_x": [],
                "midpoint_y": [],
                "geometry": [],
            },
            geometry="geometry",
            crs=config.MAP_CRS,
        )

    x_coords, y_coords = _build_pixel_centers(bounds, water_mask.shape, resolution_m)
    x_flat = x_coords.ravel()
    y_flat = y_coords.ravel()
    water_flat = water_mask.ravel().astype(bool)
    fvc_flat = fvc.ravel()
    precipitation_flat = precipitation.ravel()
    land_use_flat = land_use_intensity.ravel()

    for line_id, line in enumerate(merged_lines):
        for segment_index, segment in enumerate(_split_line(line, segment_length_m)):
            if segment.length <= 0:
                continue
            stats = _segment_stats(
                segment=segment,
                buffer_m=stat_buffer_m,
                x_flat=x_flat,
                y_flat=y_flat,
                water_flat=water_flat,
                fvc_flat=fvc_flat,
                precipitation_flat=precipitation_flat,
                land_use_flat=land_use_flat,
                resolution_m=resolution_m,
            )
            midpoint = segment.interpolate(segment.length / 2.0)
            rows.append(
                {
                    "year": year,
                    "line_id": line_id,
                    "segment_index": segment_index,
                    "segment_length_m": float(segment.length),
                    "mean_width_m": stats["mean_width_m"],
                    "fvc_mean": stats["fvc_mean"],
                    "precipitation_mean": stats["precipitation_mean"],
                    "land_use_intensity_mean": stats["land_use_intensity_mean"],
                    "midpoint_x": float(midpoint.x),
                    "midpoint_y": float(midpoint.y),
                    "geometry": segment,
                }
            )

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.MAP_CRS)


def build_response_zones(segment_metrics: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    if segment_metrics.empty:
        return gpd.GeoDataFrame(
            {
                "year_start": [],
                "year_end": [],
                "period_label": [],
                "line_id": [],
                "segment_index": [],
                "response_class": [],
                "delta_fvc": [],
                "delta_migration": [],
                "geometry": [],
            },
            geometry="geometry",
            crs=config.MAP_CRS,
        )

    ordered = segment_metrics.sort_values(["line_id", "segment_index", "year"]).reset_index(drop=True)
    for (_, _), group in ordered.groupby(["line_id", "segment_index"], sort=True):
        previous = None
        for row in group.itertuples(index=False):
            if previous is None:
                previous = row
                continue
            previous_midpoint = Point(previous.midpoint_x, previous.midpoint_y)
            current_midpoint = Point(row.midpoint_x, row.midpoint_y)
            delta_fvc = _safe_float(row.fvc_mean) - _safe_float(previous.fvc_mean)
            delta_migration = float(previous_midpoint.distance(current_midpoint))
            response_class = classify_response(delta_fvc, delta_migration)
            record = SegmentResponseRecord(
                year=int(row.year),
                period_label=f"{int(previous.year)}-{int(row.year)}",
                line_id=int(row.line_id),
                segment_index=int(row.segment_index),
                response_class=response_class,
                delta_fvc=delta_fvc,
                delta_migration=delta_migration,
            )
            payload = record.to_dict()
            payload.update(
                {
                    "year_start": int(previous.year),
                    "year_end": int(row.year),
                    "geometry": row.geometry,
                }
            )
            rows.append(payload)
            previous = row

    if not rows:
        return gpd.GeoDataFrame(
            {
                "year_start": [],
                "year_end": [],
                "period_label": [],
                "line_id": [],
                "segment_index": [],
                "response_class": [],
                "delta_fvc": [],
                "delta_migration": [],
                "geometry": [],
            },
            geometry="geometry",
            crs=config.MAP_CRS,
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=config.MAP_CRS)


def classify_response(delta_fvc: float, delta_migration: float) -> str:
    if delta_fvc >= config.RESPONSE_RECOVERY_DELTA_FVC and delta_migration <= config.RESPONSE_HIGH_MIGRATION_M:
        return "recovery"
    if delta_fvc <= config.RESPONSE_DEGRADATION_DELTA_FVC or delta_migration >= config.RESPONSE_HIGH_MIGRATION_M:
        return "degradation"
    return "stable"


def _merged_lines(centerlines_gdf: gpd.GeoDataFrame) -> list[LineString]:
    if centerlines_gdf.empty:
        return []
    union_geometry = (
        centerlines_gdf.geometry.union_all()
        if hasattr(centerlines_gdf.geometry, "union_all")
        else centerlines_gdf.geometry.unary_union
    )
    merged = linemerge(union_geometry)
    if isinstance(merged, LineString):
        return [merged]
    if isinstance(merged, MultiLineString):
        return [line for line in merged.geoms if isinstance(line, LineString)]
    return []


def _split_line(line: LineString, segment_length_m: float) -> list[LineString]:
    if line.length <= segment_length_m:
        return [line]
    segments: list[LineString] = []
    start = 0.0
    while start < line.length:
        end = min(line.length, start + segment_length_m)
        segment = substring(line, start, end)
        if isinstance(segment, LineString) and segment.length > 0:
            segments.append(segment)
        start = end
    return segments


def _build_pixel_centers(
    bounds: tuple[float, float, float, float],
    shape: tuple[int, int],
    resolution_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    rows, cols = shape
    x_min, _, _, y_max = bounds
    x = x_min + ((np.arange(cols) + 0.5) * resolution_m)
    y = y_max - ((np.arange(rows) + 0.5) * resolution_m)
    return np.meshgrid(x, y)


def _segment_stats(
    segment: LineString,
    buffer_m: float,
    x_flat: np.ndarray,
    y_flat: np.ndarray,
    water_flat: np.ndarray,
    fvc_flat: np.ndarray,
    precipitation_flat: np.ndarray,
    land_use_flat: np.ndarray,
    resolution_m: float,
) -> dict[str, float]:
    buffered = segment.buffer(buffer_m)
    min_x, min_y, max_x, max_y = buffered.bounds
    candidate_mask = (
        (x_flat >= min_x)
        & (x_flat <= max_x)
        & (y_flat >= min_y)
        & (y_flat <= max_y)
    )
    if not candidate_mask.any():
        return {
            "mean_width_m": float("nan"),
            "fvc_mean": float("nan"),
            "precipitation_mean": float("nan"),
            "land_use_intensity_mean": float("nan"),
        }

    point_series = gpd.GeoSeries(
        gpd.points_from_xy(x_flat[candidate_mask], y_flat[candidate_mask]),
        crs=config.MAP_CRS,
    )
    inside = point_series.within(buffered).to_numpy()
    if not inside.any():
        return {
            "mean_width_m": float("nan"),
            "fvc_mean": float("nan"),
            "precipitation_mean": float("nan"),
            "land_use_intensity_mean": float("nan"),
        }

    inside_water = water_flat[candidate_mask][inside]
    water_area = float(inside_water.sum()) * (resolution_m * resolution_m)
    mean_width_m = water_area / max(segment.length, resolution_m)
    inside_fvc = np.where(~inside_water, fvc_flat[candidate_mask][inside], np.nan)

    return {
        "mean_width_m": float(mean_width_m),
        "fvc_mean": float(np.nanmean(inside_fvc)),
        "precipitation_mean": float(np.nanmean(precipitation_flat[candidate_mask][inside])),
        "land_use_intensity_mean": float(np.nanmean(land_use_flat[candidate_mask][inside])),
    }


def _safe_float(value: object) -> float:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return 0.0
    return float(value)
