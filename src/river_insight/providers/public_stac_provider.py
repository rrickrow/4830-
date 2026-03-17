from __future__ import annotations

import calendar
import json
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from shapely.geometry import box

from river_insight import config
from river_insight.domain.models import (
    AnalysisRequest,
    DriverBundle,
    ObservationBundle,
    ProviderHealth,
    RasterObservation,
)
from river_insight.providers.aoi import get_study_area_boundary


@dataclass(frozen=True, slots=True)
class _GridSpec:
    size: int
    bounds_map: tuple[float, float, float, float]
    bounds_wgs84: tuple[float, float, float, float]
    transform: Any
    resolution_m: float
    aoi_mask: np.ndarray


@dataclass(frozen=True, slots=True)
class _OpticalPayload:
    blue_band: np.ndarray
    green_band: np.ndarray
    red_band: np.ndarray
    nir_band: np.ndarray
    qa_mask: np.ndarray
    valid_ratio: float
    source_summary: dict[str, Any]
    native_resolutions_m: dict[str, float]


class PublicStacProvider:
    provider_name = "public_stac"

    def __init__(
        self,
        app_config: config.AppConfig | None = None,
        catalog: Any | None = None,
        client_factory: Callable[[str], Any] | None = None,
        item_signer: Callable[[Any], Any] | None = None,
        asset_reader: Callable[[str | Path, _GridSpec, Resampling, str], tuple[np.ndarray, float | None]]
        | None = None,
        url_exists: Callable[[str], bool] | None = None,
        today_fn: Callable[[], date] | None = None,
    ) -> None:
        self.app_config = app_config or config.load_app_config()
        self._catalog = catalog
        self._client_factory = client_factory
        self._item_signer = item_signer
        self._asset_reader = asset_reader or self._read_asset_to_grid
        self._url_exists = url_exists or self._default_url_exists
        self._today_fn = today_fn or date.today

    def health_check(self, request: AnalysisRequest) -> ProviderHealth:
        try:
            catalog = self._open_catalog()
            boundary = get_study_area_boundary(request.study_area, str(self.app_config.aoi_path))
            bbox_wgs84 = tuple(float(value) for value in boundary.to_crs(config.DISPLAY_CRS).total_bounds)

            landsat_items = self._select_landsat_items(
                self._search_items(
                    catalog,
                    config.PUBLIC_STAC_COLLECTIONS["landsat"],
                    bbox_wgs84,
                    self._season_datetime_range(request.start_year, request.season_months),
                )
            )
            dem_items = self._search_items(
                catalog,
                config.PUBLIC_STAC_COLLECTIONS["dem"],
                bbox_wgs84,
            )
            landcover_items = self._search_items(
                catalog,
                config.PUBLIC_STAC_COLLECTIONS["landcover_cci"],
                bbox_wgs84,
                self._year_datetime_range(request.start_year),
            )

            signed_access = False
            sample_item_ids = {
                "landsat": [item.id for item in landsat_items[:3]],
                "dem": [item.id for item in dem_items[:3]],
                "landcover": [item.id for item in landcover_items[:3]],
            }
            if landsat_items:
                signed_item = self._sign_item(landsat_items[0])
                sample_href = signed_item.assets["green"].href
                signed_access = "sig=" in sample_href or self._url_exists(sample_href)

            chirps_source = self._resolve_chirps_source(request.start_year, request.season_months[0])
            checks_ok = bool(landsat_items and dem_items and landcover_items and chirps_source["available"])

            return ProviderHealth(
                provider_name=self.provider_name,
                status="ok" if checks_ok else "warning",
                message="公开 STAC 数据源可用" if checks_ok else "公开数据目录可访问，但存在部分回退或缺口",
                available_years=request.years,
                details={
                    "catalog_url": self.app_config.stac_catalog_url,
                    "collections": config.PUBLIC_STAC_COLLECTIONS,
                    "precipitation_source": chirps_source["version"],
                    "sample_item_ids": sample_item_ids,
                    "signed_access": signed_access,
                    "fallbacks": chirps_source.get("fallbacks", []),
                },
            )
        except Exception as exc:
            return ProviderHealth(
                provider_name=self.provider_name,
                status="error",
                message=f"公开 STAC 数据源健康检查失败: {exc}",
                available_years=request.years,
                details={"catalog_url": self.app_config.stac_catalog_url},
            )

    def load_observation_bundle(self, request: AnalysisRequest) -> ObservationBundle:
        boundary = get_study_area_boundary(request.study_area, str(self.app_config.aoi_path))
        grid = self._build_grid(boundary)
        cached_bundle = self._load_cached_bundle(request, boundary, grid)
        if cached_bundle is not None:
            return cached_bundle

        catalog = self._open_catalog()
        dem, dem_summary = self._load_dem(catalog, grid)

        year_payloads: dict[int, dict[str, Any]] = {}
        source_inventory: dict[str, Any] = {
            "provider": self.provider_name,
            "catalog_url": self.app_config.stac_catalog_url,
            "grid_size": grid.size,
            "grid_bounds_map": list(grid.bounds_map),
            "preview_bounds_wgs84": list(grid.bounds_wgs84),
            "years": {},
        }
        preview_rgb_by_year: dict[int, np.ndarray] = {}

        for year in request.years:
            optical = self._load_optical_payload(catalog, request, grid, year)
            precipitation, precipitation_summary = self._load_precipitation(grid, year, request.season_months)
            land_use, landcover_summary = self._load_land_use_intensity(catalog, grid, year)
            source_inventory["years"][str(year)] = {
                "optical": optical.source_summary if optical is not None else None,
                "dem": dem_summary,
                "landcover": landcover_summary,
                "precipitation": precipitation_summary,
                "interpolated": False,
            }
            year_payloads[year] = {
                "optical": optical,
                "dem": dem,
                "precipitation": precipitation,
                "land_use": land_use,
                "landcover_summary": landcover_summary,
                "precipitation_summary": precipitation_summary,
            }

        self._interpolate_missing_optical(year_payloads, source_inventory)

        observations: dict[int, RasterObservation] = {}
        for year in request.years:
            optical = year_payloads[year]["optical"]
            if optical is None:
                raise RuntimeError(f"{year} 年缺少可用光学影像，且无法通过插值补齐")
            metadata = {
                "provider": self.provider_name,
                "sources": optical.source_summary.get("collections", []),
                "native_resolutions_m": {
                    **optical.native_resolutions_m,
                    "dem": dem_summary.get("native_resolution_m"),
                    "landcover": year_payloads[year]["landcover_summary"].get("native_resolution_m"),
                    "precipitation": year_payloads[year]["precipitation_summary"].get("native_resolution_m"),
                },
                "landcover_source_year": year_payloads[year]["landcover_summary"].get("source_year"),
                "interpolated": bool(source_inventory["years"][str(year)]["interpolated"]),
                "source_year_summary": source_inventory["years"][str(year)],
                "preview_bounds_wgs84": list(grid.bounds_wgs84),
            }
            observation = RasterObservation(
                year=year,
                bounds=grid.bounds_map,
                resolution_m=grid.resolution_m,
                blue_band=optical.blue_band,
                green_band=optical.green_band,
                red_band=optical.red_band,
                nir_band=optical.nir_band,
                dem=year_payloads[year]["dem"],
                precipitation=year_payloads[year]["precipitation"],
                land_use_intensity=year_payloads[year]["land_use"],
                qa_mask=optical.qa_mask & grid.aoi_mask,
                metadata=metadata,
            )
            observations[year] = observation
            self._write_cached_observation(request, observation)
            if self.app_config.enable_true_color_preview:
                preview_rgb_by_year[year] = self._build_true_color_preview(observation)

        return ObservationBundle(
            provider_name=self.provider_name,
            study_area=request.study_area,
            boundary_gdf=boundary,
            observations=observations,
            metadata={
                "season_months": list(request.season_months),
                "composite_strategy": request.composite_strategy,
                "cache_enabled": request.use_cache,
                "source_inventory": source_inventory,
                "preview_rgb_by_year": preview_rgb_by_year,
                "preview_bounds_wgs84": list(grid.bounds_wgs84),
                "analysis_grid": {
                    "size": grid.size,
                    "bounds_map": list(grid.bounds_map),
                    "bounds_wgs84": list(grid.bounds_wgs84),
                    "resolution_m": grid.resolution_m,
                },
            },
        )

    def load_driver_bundle(
        self,
        request: AnalysisRequest,
        observations: dict[int, RasterObservation],
    ) -> DriverBundle:
        rows: list[dict[str, float]] = []
        for year in request.years:
            obs = observations[year]
            valid = obs.qa_mask.astype(bool)
            rows.append(
                {
                    "year": year,
                    "precipitation_mean": float(np.nanmean(np.where(valid, obs.precipitation, np.nan))),
                    "land_use_intensity_mean": float(
                        np.nanmean(np.where(valid, obs.land_use_intensity, np.nan))
                    ),
                }
            )
        return DriverBundle(
            provider_name=self.provider_name,
            table=pd.DataFrame(rows),
            metadata={"source": "public-stac"},
        )

    def _load_cached_bundle(
        self,
        request: AnalysisRequest,
        boundary,
        grid: _GridSpec,
    ) -> ObservationBundle | None:
        if not request.use_cache:
            return None
        observations: dict[int, RasterObservation] = {}
        for year in request.years:
            cached = self._load_cached_observation(request, year)
            if cached is None:
                return None
            observations[year] = cached

        preview_rgb_by_year = (
            {year: self._build_true_color_preview(observation) for year, observation in observations.items()}
            if self.app_config.enable_true_color_preview
            else {}
        )
        source_inventory = {
            "provider": self.provider_name,
            "catalog_url": self.app_config.stac_catalog_url,
            "grid_size": grid.size,
            "grid_bounds_map": list(grid.bounds_map),
            "preview_bounds_wgs84": list(grid.bounds_wgs84),
            "years": {
                str(year): observation.metadata.get("source_year_summary", {})
                for year, observation in observations.items()
            },
        }
        return ObservationBundle(
            provider_name=self.provider_name,
            study_area=request.study_area,
            boundary_gdf=boundary,
            observations=observations,
            metadata={
                "season_months": list(request.season_months),
                "composite_strategy": request.composite_strategy,
                "cache_enabled": True,
                "source_inventory": source_inventory,
                "preview_rgb_by_year": preview_rgb_by_year,
                "preview_bounds_wgs84": list(grid.bounds_wgs84),
                "analysis_grid": {
                    "size": grid.size,
                    "bounds_map": list(grid.bounds_map),
                    "bounds_wgs84": list(grid.bounds_wgs84),
                    "resolution_m": grid.resolution_m,
                },
            },
        )

    def _cache_path(self, request: AnalysisRequest, year: int) -> Path:
        season_key = f"{request.season_months[0]:02d}{request.season_months[1]:02d}"
        return (
            self.app_config.cache_root
            / self.provider_name
            / request.study_area
            / f"{year}_{season_key}_{request.composite_strategy}_{self.app_config.analysis_grid_size}.npz"
        )

    def _load_cached_observation(
        self,
        request: AnalysisRequest,
        year: int,
    ) -> RasterObservation | None:
        cache_path = self._cache_path(request, year)
        if not cache_path.exists():
            return None
        with np.load(cache_path, allow_pickle=True) as archive:
            metadata = json.loads(str(archive["metadata"].item()))
            blue_band = archive["blue_band"] if "blue_band" in archive.files else None
            if isinstance(blue_band, np.ndarray) and blue_band.size == 0:
                blue_band = None
            return RasterObservation(
                year=int(archive["year"].item()),
                bounds=tuple(float(item) for item in archive["bounds"]),
                resolution_m=float(archive["resolution_m"].item()),
                blue_band=blue_band,
                green_band=archive["green_band"],
                red_band=archive["red_band"],
                nir_band=archive["nir_band"],
                dem=archive["dem"],
                precipitation=archive["precipitation"],
                land_use_intensity=archive["land_use_intensity"],
                qa_mask=archive["qa_mask"].astype(bool),
                metadata=metadata,
            )

    def _write_cached_observation(self, request: AnalysisRequest, observation: RasterObservation) -> None:
        if not request.use_cache:
            return
        cache_path = self._cache_path(request, observation.year)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            cache_path,
            year=np.asarray(observation.year),
            bounds=np.asarray(observation.bounds, dtype=float),
            resolution_m=np.asarray(observation.resolution_m),
            blue_band=observation.blue_band if observation.blue_band is not None else np.asarray([]),
            green_band=observation.green_band,
            red_band=observation.red_band,
            nir_band=observation.nir_band,
            dem=observation.dem,
            precipitation=observation.precipitation,
            land_use_intensity=observation.land_use_intensity,
            qa_mask=observation.qa_mask.astype(np.uint8),
            metadata=np.asarray(json.dumps(observation.metadata, ensure_ascii=False)),
        )

    def _open_catalog(self) -> Any:
        if self._catalog is not None:
            return self._catalog
        if self._client_factory is not None:
            self._catalog = self._client_factory(self.app_config.stac_catalog_url)
            return self._catalog
        try:
            from pystac_client import Client
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "当前环境未安装 pystac-client，请先执行 `python -m pip install -r requirements.txt`"
            ) from exc
        self._catalog = Client.open(self.app_config.stac_catalog_url)
        return self._catalog

    def _sign_item(self, item: Any) -> Any:
        if self._item_signer is not None:
            return self._item_signer(item)
        try:
            import planetary_computer
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "当前环境未安装 planetary-computer，请先执行 `python -m pip install -r requirements.txt`"
            ) from exc
        return planetary_computer.sign(item)

    def _build_grid(self, boundary) -> _GridSpec:
        geometry = (
            boundary.geometry.union_all()
            if hasattr(boundary.geometry, "union_all")
            else boundary.geometry.unary_union
        )
        min_x, min_y, max_x, max_y = (float(value) for value in boundary.total_bounds)
        width = max_x - min_x
        height = max_y - min_y
        side = max(width, height)
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        half = side / 2.0
        bounds_map = (center_x - half, center_y - half, center_x + half, center_y + half)
        transform = from_bounds(*bounds_map, self.app_config.analysis_grid_size, self.app_config.analysis_grid_size)
        resolution_m = side / float(self.app_config.analysis_grid_size)
        aoi_mask = geometry_mask(
            [geometry.__geo_interface__],
            out_shape=(self.app_config.analysis_grid_size, self.app_config.analysis_grid_size),
            transform=transform,
            invert=True,
        )
        display_box = boundary.__class__(geometry=[box(*bounds_map)], crs=config.MAP_CRS).to_crs(config.DISPLAY_CRS)
        bounds_wgs84 = tuple(float(value) for value in display_box.total_bounds)
        return _GridSpec(
            size=self.app_config.analysis_grid_size,
            bounds_map=bounds_map,
            bounds_wgs84=bounds_wgs84,
            transform=transform,
            resolution_m=resolution_m,
            aoi_mask=aoi_mask,
        )

    def _load_dem(self, catalog: Any, grid: _GridSpec) -> tuple[np.ndarray, dict[str, Any]]:
        items = self._search_items(catalog, config.PUBLIC_STAC_COLLECTIONS["dem"], grid.bounds_wgs84)
        if not items:
            raise RuntimeError("Copernicus DEM 未命中研究区")
        arrays: list[np.ndarray] = []
        native_resolutions: list[float] = []
        signed_items = [self._sign_item(item) for item in items]
        for item in signed_items:
            data, native_resolution = self._asset_reader(
                item.assets["data"].href,
                grid,
                Resampling.bilinear,
                "dem",
            )
            data = np.where(grid.aoi_mask, data, np.nan)
            arrays.append(data)
            if native_resolution is not None:
                native_resolutions.append(native_resolution)
        dem = self._nanmean_stack(arrays)
        return dem, {
            "collection": config.PUBLIC_STAC_COLLECTIONS["dem"],
            "item_ids": [item.id for item in items],
            "asset_names": ["data"],
            "native_resolution_m": float(np.nanmean(native_resolutions)) if native_resolutions else None,
        }

    def _load_land_use_intensity(
        self,
        catalog: Any,
        grid: _GridSpec,
        year: int,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if year <= 2020:
            collection_name = config.PUBLIC_STAC_COLLECTIONS["landcover_cci"]
            asset_name = "lccs_class"
            source_year = year
            items = self._search_items(
                catalog,
                collection_name,
                grid.bounds_wgs84,
                self._year_datetime_range(year),
            )
            mapper = self._map_esa_cci_to_intensity
        else:
            collection_name = config.PUBLIC_STAC_COLLECTIONS["landcover_worldcover"]
            asset_name = "map"
            source_year = 2021
            items = self._search_items(
                catalog,
                collection_name,
                grid.bounds_wgs84,
                self._year_datetime_range(2021),
            )
            mapper = self._map_worldcover_to_intensity
        if not items:
            raise RuntimeError(f"{source_year} 年土地覆盖数据未命中研究区")

        signed_items = [self._sign_item(item) for item in items]
        class_layers: list[np.ndarray] = []
        native_resolutions: list[float] = []
        for item in signed_items:
            classes, native_resolution = self._asset_reader(
                item.assets[asset_name].href,
                grid,
                Resampling.nearest,
                asset_name,
            )
            class_layers.append(classes)
            if native_resolution is not None:
                native_resolutions.append(native_resolution)

        class_grid = self._merge_class_layers(class_layers, grid.aoi_mask)
        land_use = mapper(class_grid)
        return land_use, {
            "collection": collection_name,
            "item_ids": [item.id for item in items],
            "asset_names": [asset_name],
            "source_year": source_year,
            "native_resolution_m": float(np.nanmean(native_resolutions)) if native_resolutions else None,
        }

    def _load_precipitation(
        self,
        grid: _GridSpec,
        year: int,
        season_months: tuple[int, int],
    ) -> tuple[np.ndarray, dict[str, Any]]:
        layers: list[np.ndarray] = []
        urls: list[str] = []
        fallbacks: list[str] = []
        native_resolutions: list[float] = []
        version = "v3"

        for month in range(season_months[0], season_months[1] + 1):
            source = self._resolve_chirps_source(year, month)
            version = source["version"]
            urls.append(source["url"])
            fallbacks.extend(source.get("fallbacks", []))
            local_path = self._download_precipitation_file(source["url"], version, year, month)
            precip, native_resolution = self._asset_reader(
                local_path,
                grid,
                Resampling.bilinear,
                "precipitation",
            )
            layers.append(np.where(grid.aoi_mask, precip, np.nan))
            if native_resolution is not None:
                native_resolutions.append(native_resolution)

        precipitation = np.nansum(np.stack(layers, axis=0), axis=0)
        return precipitation, {
            "version": version,
            "urls": urls,
            "fallback_used": bool(fallbacks),
            "fallbacks": fallbacks,
            "native_resolution_m": float(np.nanmean(native_resolutions)) if native_resolutions else None,
        }

    def _load_optical_payload(
        self,
        catalog: Any,
        request: AnalysisRequest,
        grid: _GridSpec,
        year: int,
    ) -> _OpticalPayload | None:
        season_range = self._season_datetime_range(year, request.season_months)
        landsat_items = self._select_landsat_items(
            self._search_items(catalog, config.PUBLIC_STAC_COLLECTIONS["landsat"], grid.bounds_wgs84, season_range)
        )
        landsat_payloads = [self._read_landsat_item(item, grid) for item in landsat_items]
        landsat_payloads = [payload for payload in landsat_payloads if payload is not None]

        chosen_payloads = list(landsat_payloads)
        if year >= 2017:
            sentinel_items = self._select_sentinel_items(
                self._search_items(
                    catalog,
                    config.PUBLIC_STAC_COLLECTIONS["sentinel"],
                    grid.bounds_wgs84,
                    season_range,
                )
            )
            sentinel_payloads = [self._read_sentinel_item(item, grid) for item in sentinel_items]
            sentinel_payloads = [payload for payload in sentinel_payloads if payload is not None]
            sentinel_valid_ratio = self._composite_valid_ratio(sentinel_payloads)
            if sentinel_payloads and sentinel_valid_ratio >= 0.08:
                chosen_payloads.extend(sentinel_payloads)

        if not chosen_payloads:
            return None

        return self._compose_optical_payload(chosen_payloads, request.composite_strategy)

    def _read_landsat_item(self, item: Any, grid: _GridSpec) -> _OpticalPayload | None:
        signed_item = self._sign_item(item)
        asset_map = {
            "blue_band": "blue",
            "green_band": "green",
            "red_band": "red",
            "nir_band": "nir08",
            "qa_mask": "qa_pixel",
        }
        arrays: dict[str, np.ndarray] = {}
        native_resolutions: dict[str, float] = {}
        for field_name, asset_name in asset_map.items():
            resampling = Resampling.nearest if asset_name == "qa_pixel" else Resampling.bilinear
            array, native_resolution = self._asset_reader(
                signed_item.assets[asset_name].href,
                grid,
                resampling,
                asset_name,
            )
            arrays[field_name] = array
            if native_resolution is not None:
                native_resolutions[asset_name] = native_resolution

        clear_mask = self._landsat_clear_mask(arrays["qa_mask"]) & grid.aoi_mask
        blue = np.where(clear_mask, (arrays["blue_band"] * 0.0000275) - 0.2, np.nan)
        green = np.where(clear_mask, (arrays["green_band"] * 0.0000275) - 0.2, np.nan)
        red = np.where(clear_mask, (arrays["red_band"] * 0.0000275) - 0.2, np.nan)
        nir = np.where(clear_mask, (arrays["nir_band"] * 0.0000275) - 0.2, np.nan)
        qa_mask = np.isfinite(blue) & np.isfinite(green) & np.isfinite(red) & np.isfinite(nir)
        if not qa_mask.any():
            return None
        return _OpticalPayload(
            blue_band=np.clip(blue, 0.0, 1.0),
            green_band=np.clip(green, 0.0, 1.0),
            red_band=np.clip(red, 0.0, 1.0),
            nir_band=np.clip(nir, 0.0, 1.0),
            qa_mask=qa_mask,
            valid_ratio=float(np.mean(qa_mask)),
            source_summary={
                "collections": [config.PUBLIC_STAC_COLLECTIONS["landsat"]],
                "item_ids": [item.id],
                "asset_names": ["blue", "green", "red", "nir08", "qa_pixel"],
            },
            native_resolutions_m=native_resolutions,
        )

    def _read_sentinel_item(self, item: Any, grid: _GridSpec) -> _OpticalPayload | None:
        signed_item = self._sign_item(item)
        asset_map = {
            "blue_band": "B02",
            "green_band": "B03",
            "red_band": "B04",
            "nir_band": "B08",
            "qa_mask": "SCL",
        }
        arrays: dict[str, np.ndarray] = {}
        native_resolutions: dict[str, float] = {}
        for field_name, asset_name in asset_map.items():
            resampling = Resampling.nearest if asset_name == "SCL" else Resampling.bilinear
            array, native_resolution = self._asset_reader(
                signed_item.assets[asset_name].href,
                grid,
                resampling,
                asset_name,
            )
            arrays[field_name] = array
            if native_resolution is not None:
                native_resolutions[asset_name] = native_resolution

        clear_mask = self._sentinel_clear_mask(arrays["qa_mask"]) & grid.aoi_mask
        blue = np.where(clear_mask, arrays["blue_band"] * 0.0001, np.nan)
        green = np.where(clear_mask, arrays["green_band"] * 0.0001, np.nan)
        red = np.where(clear_mask, arrays["red_band"] * 0.0001, np.nan)
        nir = np.where(clear_mask, arrays["nir_band"] * 0.0001, np.nan)
        qa_mask = np.isfinite(blue) & np.isfinite(green) & np.isfinite(red) & np.isfinite(nir)
        if not qa_mask.any():
            return None
        return _OpticalPayload(
            blue_band=np.clip(blue, 0.0, 1.0),
            green_band=np.clip(green, 0.0, 1.0),
            red_band=np.clip(red, 0.0, 1.0),
            nir_band=np.clip(nir, 0.0, 1.0),
            qa_mask=qa_mask,
            valid_ratio=float(np.mean(qa_mask)),
            source_summary={
                "collections": [config.PUBLIC_STAC_COLLECTIONS["sentinel"]],
                "item_ids": [item.id],
                "asset_names": ["B02", "B03", "B04", "B08", "SCL"],
            },
            native_resolutions_m=native_resolutions,
        )

    def _compose_optical_payload(
        self,
        payloads: list[_OpticalPayload],
        strategy: str,
    ) -> _OpticalPayload:
        reducer = np.nanmean if strategy == "mean" else np.nanmedian
        blue = reducer(np.stack([payload.blue_band for payload in payloads], axis=0), axis=0)
        green = reducer(np.stack([payload.green_band for payload in payloads], axis=0), axis=0)
        red = reducer(np.stack([payload.red_band for payload in payloads], axis=0), axis=0)
        nir = reducer(np.stack([payload.nir_band for payload in payloads], axis=0), axis=0)
        qa_mask = np.isfinite(blue) & np.isfinite(green) & np.isfinite(red) & np.isfinite(nir)

        collection_names: list[str] = []
        item_ids: list[str] = []
        asset_names: list[str] = []
        native_resolutions: dict[str, float] = {}
        for payload in payloads:
            collection_names.extend(payload.source_summary.get("collections", []))
            item_ids.extend(payload.source_summary.get("item_ids", []))
            asset_names.extend(payload.source_summary.get("asset_names", []))
            native_resolutions.update(payload.native_resolutions_m)

        return _OpticalPayload(
            blue_band=np.clip(blue, 0.0, 1.0),
            green_band=np.clip(green, 0.0, 1.0),
            red_band=np.clip(red, 0.0, 1.0),
            nir_band=np.clip(nir, 0.0, 1.0),
            qa_mask=qa_mask,
            valid_ratio=float(np.mean(qa_mask)),
            source_summary={
                "collections": sorted(set(collection_names)),
                "item_ids": sorted(set(item_ids)),
                "asset_names": sorted(set(asset_names)),
            },
            native_resolutions_m=native_resolutions,
        )

    def _interpolate_missing_optical(
        self,
        year_payloads: dict[int, dict[str, Any]],
        source_inventory: dict[str, Any],
    ) -> None:
        years = sorted(year_payloads)
        available = [year for year in years if year_payloads[year]["optical"] is not None]
        for year in years:
            if year_payloads[year]["optical"] is not None:
                continue
            lower_candidates = [value for value in available if value < year]
            upper_candidates = [value for value in available if value > year]
            if not lower_candidates or not upper_candidates:
                continue
            lower_year = lower_candidates[-1]
            upper_year = upper_candidates[0]
            lower = year_payloads[lower_year]["optical"]
            upper = year_payloads[upper_year]["optical"]
            if lower is None or upper is None:
                continue
            ratio = (year - lower_year) / float(upper_year - lower_year)
            qa_mask = ((1.0 - ratio) * lower.qa_mask.astype(float) + (ratio * upper.qa_mask.astype(float))) > 0.5
            interpolated = _OpticalPayload(
                blue_band=((1.0 - ratio) * lower.blue_band) + (ratio * upper.blue_band),
                green_band=((1.0 - ratio) * lower.green_band) + (ratio * upper.green_band),
                red_band=((1.0 - ratio) * lower.red_band) + (ratio * upper.red_band),
                nir_band=((1.0 - ratio) * lower.nir_band) + (ratio * upper.nir_band),
                qa_mask=qa_mask,
                valid_ratio=float(np.mean(qa_mask)),
                source_summary={
                    "collections": sorted(
                        set(
                            [
                                *lower.source_summary.get("collections", []),
                                *upper.source_summary.get("collections", []),
                            ]
                        )
                    ),
                    "item_ids": sorted(
                        set(
                            [
                                *lower.source_summary.get("item_ids", []),
                                *upper.source_summary.get("item_ids", []),
                            ]
                        )
                    ),
                    "asset_names": sorted(
                        set(
                            [
                                *lower.source_summary.get("asset_names", []),
                                *upper.source_summary.get("asset_names", []),
                            ]
                        )
                    ),
                },
                native_resolutions_m={**lower.native_resolutions_m, **upper.native_resolutions_m},
            )
            year_payloads[year]["optical"] = interpolated
            source_inventory["years"][str(year)]["interpolated"] = True
            source_inventory["years"][str(year)]["optical"] = {
                **interpolated.source_summary,
                "interpolated": True,
                "lower_year": lower_year,
                "upper_year": upper_year,
            }

    def _search_items(
        self,
        catalog: Any,
        collection_name: str,
        bbox_wgs84: tuple[float, float, float, float],
        datetime_range: str | None = None,
    ) -> list[Any]:
        search = catalog.search(
            collections=[collection_name],
            bbox=list(bbox_wgs84),
            datetime=datetime_range,
            max_items=120,
        )
        return list(search.items())

    def _select_landsat_items(self, items: list[Any]) -> list[Any]:
        filtered = [
            item
            for item in items
            if float(item.properties.get("eo:cloud_cover", 100.0)) <= self.app_config.landsat_max_cloud_cover
        ]
        return self._limit_items_by_tile(
            filtered,
            lambda item: (
                item.properties.get("landsat:wrs_path"),
                item.properties.get("landsat:wrs_row"),
            ),
        )

    def _select_sentinel_items(self, items: list[Any]) -> list[Any]:
        filtered = [
            item
            for item in items
            if float(item.properties.get("eo:cloud_cover", 100.0)) <= self.app_config.sentinel_max_cloud_cover
        ]
        return self._limit_items_by_tile(
            filtered,
            lambda item: item.properties.get("s2:mgrs_tile"),
        )

    @staticmethod
    def _limit_items_by_tile(
        items: list[Any],
        tile_key: Callable[[Any], Any],
        per_tile_limit: int = 1,
        total_limit: int = 12,
    ) -> list[Any]:
        sorted_items = sorted(
            items,
            key=lambda item: (
                float(item.properties.get("eo:cloud_cover", 100.0)),
                item.properties.get("datetime") or "",
            ),
        )
        selected: list[Any] = []
        counts: dict[Any, int] = {}
        for item in sorted_items:
            key = tile_key(item)
            if counts.get(key, 0) >= per_tile_limit:
                continue
            selected.append(item)
            counts[key] = counts.get(key, 0) + 1
            if len(selected) >= total_limit:
                break
        return selected

    def _resolve_chirps_source(self, year: int, month: int) -> dict[str, Any]:
        v3_url = f"{config.CHIRPS_V3_BASE_URL}/chirps-v3.0.{year}.{month:02d}.cog"
        if self._url_exists(v3_url):
            return {"version": "v3", "url": v3_url, "available": True, "fallbacks": []}

        fallbacks = [f"{year}-{month:02d} 未命中 CHIRPS v3，回退到 CHIRPS v2"]
        v2_url = f"{config.CHIRPS_V2_BASE_URL}/chirps-v2.0.{year}.{month:02d}.cog"
        if self._today_fn() <= config.CHIRPS_V3_FALLBACK_DEADLINE and self._url_exists(v2_url):
            return {"version": "v2", "url": v2_url, "available": True, "fallbacks": fallbacks}
        raise RuntimeError(f"{year}-{month:02d} 的 CHIRPS 数据不可用")

    def _download_precipitation_file(self, url: str, version: str, year: int, month: int) -> Path:
        target = (
            self.app_config.cache_root
            / self.provider_name
            / "precipitation"
            / version
            / f"{year}_{month:02d}.cog"
        )
        if target.exists():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "river-insight/1.0"})
                with urllib.request.urlopen(request, timeout=self.app_config.request_timeout_seconds) as response:
                    with target.open("wb") as handle:
                        shutil.copyfileobj(response, handle)
                return target
            except Exception as exc:  # pragma: no cover - network variability
                last_error = exc
                if target.exists():
                    target.unlink(missing_ok=True)
                if attempt < 2:
                    time.sleep(1.0)
        raise RuntimeError(f"下载 CHIRPS 文件失败: {url} ({last_error})")

    def _read_asset_to_grid(
        self,
        href: str | Path,
        grid: _GridSpec,
        resampling: Resampling,
        band_name: str,
    ) -> tuple[np.ndarray, float | None]:
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_USE_HEAD="NO",
            GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
            GDAL_HTTP_MULTIPLEX="YES",
        ):
            with rasterio.open(str(href)) as source:
                native_resolution = float(np.mean(np.abs(source.res))) if source.res else None
                with WarpedVRT(
                    source,
                    crs=config.MAP_CRS,
                    transform=grid.transform,
                    width=grid.size,
                    height=grid.size,
                    resampling=resampling,
                ) as vrt:
                    data = vrt.read(1, masked=True)
                    array = np.asarray(data.filled(np.nan), dtype=float)
        return array, native_resolution

    @staticmethod
    def _year_datetime_range(year: int) -> str:
        return f"{year:04d}-01-01/{year:04d}-12-31"

    @staticmethod
    def _season_datetime_range(year: int, season_months: tuple[int, int]) -> str:
        end_day = calendar.monthrange(year, season_months[1])[1]
        return f"{year:04d}-{season_months[0]:02d}-01/{year:04d}-{season_months[1]:02d}-{end_day:02d}"

    @staticmethod
    def _landsat_clear_mask(qa_pixel: np.ndarray) -> np.ndarray:
        qa = np.asarray(np.nan_to_num(qa_pixel, nan=0.0), dtype=np.uint16)
        fill = (qa & (1 << 0)) != 0
        dilated_cloud = (qa & (1 << 1)) != 0
        cirrus = (qa & (1 << 2)) != 0
        cloud = (qa & (1 << 3)) != 0
        shadow = (qa & (1 << 4)) != 0
        snow = (qa & (1 << 5)) != 0
        return ~(fill | dilated_cloud | cirrus | cloud | shadow | snow)

    @staticmethod
    def _sentinel_clear_mask(scl: np.ndarray) -> np.ndarray:
        classes = np.asarray(np.nan_to_num(scl, nan=0.0), dtype=np.uint8)
        invalid = np.isin(classes, [0, 1, 3, 7, 8, 9, 10, 11])
        return ~invalid

    @staticmethod
    def _composite_valid_ratio(payloads: list[_OpticalPayload]) -> float:
        if not payloads:
            return 0.0
        mask = np.any(np.stack([payload.qa_mask for payload in payloads], axis=0), axis=0)
        return float(np.mean(mask))

    @staticmethod
    def _nanmean_stack(arrays: list[np.ndarray]) -> np.ndarray:
        if not arrays:
            return np.empty((0, 0), dtype=float)
        return np.nanmean(np.stack(arrays, axis=0), axis=0)

    @staticmethod
    def _merge_class_layers(arrays: list[np.ndarray], aoi_mask: np.ndarray) -> np.ndarray:
        merged = np.full(aoi_mask.shape, np.nan, dtype=float)
        for array in arrays:
            valid = np.isfinite(array) & aoi_mask & ~np.isfinite(merged)
            merged[valid] = array[valid]
        return merged

    @staticmethod
    def _map_esa_cci_to_intensity(classes: np.ndarray) -> np.ndarray:
        intensity = np.full(classes.shape, np.nan, dtype=float)
        class_intensity = {
            10: 0.60,
            11: 0.60,
            20: 0.60,
            30: 0.60,
            40: 0.15,
            50: 0.15,
            60: 0.15,
            61: 0.15,
            62: 0.15,
            70: 0.15,
            71: 0.15,
            72: 0.15,
            80: 0.25,
            81: 0.25,
            82: 0.25,
            90: 0.25,
            100: 0.25,
            110: 0.25,
            120: 0.25,
            121: 0.25,
            122: 0.25,
            130: 0.95,
            140: 0.05,
            150: 0.05,
            151: 0.05,
            152: 0.05,
            153: 0.05,
            160: 0.20,
            170: 0.20,
            180: 0.05,
            190: 0.95,
            200: 0.05,
            201: 0.05,
            202: 0.05,
            210: 0.05,
            220: 0.05,
        }
        for class_value, mapped in class_intensity.items():
            intensity[classes == class_value] = mapped
        return np.where(np.isfinite(intensity), intensity, 0.25)

    @staticmethod
    def _map_worldcover_to_intensity(classes: np.ndarray) -> np.ndarray:
        intensity = np.full(classes.shape, np.nan, dtype=float)
        class_intensity = {
            10: 0.15,
            20: 0.25,
            30: 0.25,
            40: 0.60,
            50: 0.95,
            60: 0.20,
            70: 0.05,
            80: 0.05,
            90: 0.25,
            95: 0.25,
            100: 0.20,
        }
        for class_value, mapped in class_intensity.items():
            intensity[classes == class_value] = mapped
        return np.where(np.isfinite(intensity), intensity, 0.25)

    @staticmethod
    def _build_true_color_preview(observation: RasterObservation) -> np.ndarray:
        blue = np.where(observation.qa_mask, observation.blue_band, np.nan)
        green = np.where(observation.qa_mask, observation.green_band, np.nan)
        red = np.where(observation.qa_mask, observation.red_band, np.nan)
        rgb = np.dstack(
            [
                np.clip((red - 0.02) / 0.28, 0.0, 1.0),
                np.clip((green - 0.02) / 0.28, 0.0, 1.0),
                np.clip((blue - 0.02) / 0.28, 0.0, 1.0),
            ]
        )
        return np.nan_to_num(rgb, nan=0.0)

    def _default_url_exists(self, url: str) -> bool:
        for attempt in range(3):
            request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "river-insight/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=self.app_config.request_timeout_seconds) as response:
                    return int(response.status) < 400
            except urllib.error.HTTPError as exc:
                if exc.code == 405:
                    try:
                        get_request = urllib.request.Request(url, headers={"User-Agent": "river-insight/1.0"})
                        with urllib.request.urlopen(
                            get_request,
                            timeout=self.app_config.request_timeout_seconds,
                        ) as response:
                            return int(response.status) < 400
                    except Exception:
                        pass
                if exc.code == 404:
                    return False
            except Exception:
                pass
            if attempt < 2:
                time.sleep(0.5)
        return False
