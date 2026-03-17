from __future__ import annotations

from functools import lru_cache

import geopandas as gpd

from river_insight import config


@lru_cache(maxsize=4)
def load_study_areas(aoi_path: str | None = None) -> gpd.GeoDataFrame:
    path = config.AOI_FILE if aoi_path is None else aoi_path
    areas = gpd.read_file(path)
    if areas.crs is None:
        areas = areas.set_crs(config.MAP_CRS)
    if str(areas.crs) != config.MAP_CRS:
        areas = areas.to_crs(config.MAP_CRS)
    return areas


def get_study_area_boundary(study_area: str, aoi_path: str | None = None) -> gpd.GeoDataFrame:
    areas = load_study_areas(aoi_path)
    boundary = areas[areas["study_area"] == study_area].copy()
    if boundary.empty:
        raise KeyError(f"未知研究区域: {study_area}")
    return boundary.reset_index(drop=True)
