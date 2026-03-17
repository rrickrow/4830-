from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

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
class _AreaProfile:
    seed: float
    phase_shift: float


class DemoProvider:
    provider_name = "demo"

    def __init__(self) -> None:
        self._profiles = {
            "songhua": _AreaProfile(0.8, 0.2),
            "liaohe": _AreaProfile(1.6, -0.15),
            "combined": _AreaProfile(2.4, 0.05),
        }

    def health_check(self, request: AnalysisRequest) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            status="ok",
            message="离线演示数据源可用",
            available_years=list(config.BASE_YEARS),
            details={"supports_network": False, "analysis_grid_size": config.RASTER_SIZE},
        )

    def load_observation_bundle(self, request: AnalysisRequest) -> ObservationBundle:
        boundary = get_study_area_boundary(request.study_area, str(config.AOI_FILE))
        observations = {
            year: self._build_or_interpolate(request.study_area, year, boundary.total_bounds)
            for year in request.years
        }
        preview_rgb_by_year = {
            year: np.dstack([observation.red_band, observation.green_band, observation.blue_band])
            for year, observation in observations.items()
            if observation.blue_band is not None
        }
        source_inventory = {
            "provider": self.provider_name,
            "grid_size": config.RASTER_SIZE,
            "preview_bounds_wgs84": list(boundary.to_crs(config.DISPLAY_CRS).total_bounds),
            "years": {
                str(year): {
                    "provider": self.provider_name,
                    "sources": ["synthetic"],
                    "interpolated": bool(observation.metadata.get("interpolated", False)),
                }
                for year, observation in observations.items()
            },
        }
        return ObservationBundle(
            provider_name=self.provider_name,
            study_area=request.study_area,
            boundary_gdf=boundary,
            observations=observations,
            metadata={
                "base_years": list(config.BASE_YEARS),
                "season_months": list(request.season_months),
                "composite_strategy": request.composite_strategy,
                "source_inventory": source_inventory,
                "preview_rgb_by_year": preview_rgb_by_year,
                "preview_bounds_wgs84": list(boundary.to_crs(config.DISPLAY_CRS).total_bounds),
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
            metadata={"source": "synthetic"},
        )

    def _build_or_interpolate(
        self,
        study_area: str,
        year: int,
        bounds: tuple[float, float, float, float],
    ) -> RasterObservation:
        if year in config.BASE_YEARS:
            return self._build_observation(study_area, year, bounds)
        lower = max(base for base in config.BASE_YEARS if base < year)
        upper = min(base for base in config.BASE_YEARS if base > year)
        ratio = (year - lower) / (upper - lower)
        low = self._build_observation(study_area, lower, bounds)
        high = self._build_observation(study_area, upper, bounds)
        return RasterObservation(
            year=year,
            bounds=low.bounds,
            resolution_m=low.resolution_m,
            blue_band=((1.0 - ratio) * low.blue_band) + (ratio * high.blue_band),
            green_band=((1.0 - ratio) * low.green_band) + (ratio * high.green_band),
            red_band=((1.0 - ratio) * low.red_band) + (ratio * high.red_band),
            nir_band=((1.0 - ratio) * low.nir_band) + (ratio * high.nir_band),
            dem=((1.0 - ratio) * low.dem) + (ratio * high.dem),
            precipitation=((1.0 - ratio) * low.precipitation) + (ratio * high.precipitation),
            land_use_intensity=((1.0 - ratio) * low.land_use_intensity)
            + (ratio * high.land_use_intensity),
            qa_mask=((1.0 - ratio) * low.qa_mask.astype(float) + (ratio * high.qa_mask.astype(float))) > 0.5,
            metadata={
                "interpolated": True,
                "lower_year": lower,
                "upper_year": upper,
                "sources": ["synthetic"],
            },
        )

    def _build_observation(
        self,
        study_area: str,
        year: int,
        bounds: tuple[float, float, float, float],
    ) -> RasterObservation:
        profile = self._profiles[self._require_area(study_area)]
        xx, yy = self._coordinate_grid()
        t = (year - config.BASE_YEARS[0]) / (config.BASE_YEARS[-1] - config.BASE_YEARS[0])

        primary_center = (
            0.12 * np.sin((xx + profile.phase_shift) * 4.6 + (t * 2.4))
            + 0.08 * np.cos((xx * 1.8) - (t * 3.0))
            + profile.phase_shift
        )
        primary_width = 0.095 + (0.02 * np.sin((t + profile.seed) * np.pi))
        main_river = np.abs(yy - primary_center) < (
            primary_width + 0.012 * np.cos(xx * 5.0)
        )

        branch = np.zeros_like(main_river)
        if study_area in {"songhua", "combined"}:
            branch_center = primary_center + 0.18 + (0.03 * np.sin((xx * 5.8) + t))
            branch = np.abs(yy - branch_center) < (primary_width * (0.36 + (0.06 * t)))
        elif study_area == "liaohe":
            branch_center = primary_center - 0.16 + (0.02 * np.cos((xx * 4.2) - t))
            branch = np.abs(yy - branch_center) < (primary_width * 0.28)

        water_mask = main_river | branch
        vegetation_base = (
            0.46
            + (0.08 * np.sin((xx + profile.seed) * 3.0))
            + (0.07 * np.cos((yy - profile.seed) * 2.6))
            + (0.04 * t)
        )
        precipitation = (
            640.0
            + (90.0 * t)
            + (25.0 * np.sin((xx * 2.0) + profile.seed))
            + (18.0 * np.cos((yy * 1.5) - profile.seed))
        )
        land_use = np.clip(
            0.20
            + (0.24 * (xx + 1.0) / 2.0)
            + (0.08 * (1.0 - (yy + 1.0) / 2.0))
            + (0.06 * t),
            0.05,
            0.95,
        )
        dem = (
            180.0
            + (70.0 * (1.0 - (yy + 1.0) / 2.0))
            + (12.0 * np.sin((xx * 2.2) + profile.seed))
            + (8.0 * np.cos((yy * 1.7) - profile.seed))
        )

        blue = np.clip(
            0.12 + (0.16 * vegetation_base) - (0.03 * land_use) + (precipitation - 650.0) / 5200.0,
            0.02,
            0.65,
        )
        green = np.clip(
            0.23 + (0.25 * vegetation_base) - (0.05 * land_use) + (precipitation - 650.0) / 4000.0,
            0.05,
            0.85,
        )
        red = np.clip(
            0.28 + (0.08 * (1.0 - vegetation_base)) + (0.03 * land_use) - (precipitation - 650.0) / 5000.0,
            0.05,
            0.75,
        )
        nir = np.clip(
            0.42 + (0.36 * vegetation_base) - (0.04 * land_use) + (precipitation - 650.0) / 3200.0,
            0.08,
            0.98,
        )

        blue = np.where(water_mask, 0.18 + (0.01 * np.sin(xx * 6.0)), blue)
        green = np.where(water_mask, 0.16 + (0.015 * np.sin(xx * 8.0)), green)
        red = np.where(water_mask, 0.07 + (0.01 * np.cos(yy * 5.0)), red)
        nir = np.where(water_mask, 0.03 + (0.008 * np.cos(yy * 7.0)), nir)

        qa_mask = self._build_qa_mask(xx, yy, t, profile.seed)
        blue = np.clip(blue, 0.0, 1.0)
        green = np.clip(green, 0.0, 1.0)
        red = np.clip(red, 0.0, 1.0)
        nir = np.clip(nir, 0.0, 1.0)

        return RasterObservation(
            year=year,
            bounds=tuple(float(item) for item in bounds),
            resolution_m=config.RESOLUTION_M,
            blue_band=blue,
            green_band=green,
            red_band=red,
            nir_band=nir,
            dem=dem,
            precipitation=precipitation,
            land_use_intensity=land_use,
            qa_mask=qa_mask,
            metadata={"interpolated": False, "provider": self.provider_name, "sources": ["synthetic"]},
        )

    @staticmethod
    def _coordinate_grid() -> tuple[np.ndarray, np.ndarray]:
        values = np.linspace(-1.0, 1.0, config.RASTER_SIZE)
        return np.meshgrid(values, values)

    @staticmethod
    def _build_qa_mask(
        xx: np.ndarray,
        yy: np.ndarray,
        t: float,
        seed: float,
    ) -> np.ndarray:
        cloud_zone = ((xx + 0.4 * seed) > 0.72) & ((yy - 0.2 * seed) < -0.55)
        stripe = np.abs(np.sin((xx * 9.0) + (t * 2.0) + seed)) > 0.995
        return ~(cloud_zone | stripe)

    def _require_area(self, study_area: str) -> str:
        if study_area not in self._profiles:
            raise KeyError(f"未知研究区: {study_area}")
        return study_area
