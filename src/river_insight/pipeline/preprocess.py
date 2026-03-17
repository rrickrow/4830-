from __future__ import annotations

from dataclasses import replace

import numpy as np

from river_insight.domain.models import AnalysisRequest, ObservationBundle, RasterObservation


def normalize_observation(observation: RasterObservation) -> RasterObservation:
    valid = observation.qa_mask.astype(bool)
    blue = None
    if observation.blue_band is not None:
        blue = np.where(valid, np.clip(observation.blue_band, 0.0, 1.0), np.nan)
    green = np.where(valid, np.clip(observation.green_band, 0.0, 1.0), np.nan)
    red = np.where(valid, np.clip(observation.red_band, 0.0, 1.0), np.nan)
    nir = np.where(valid, np.clip(observation.nir_band, 0.0, 1.0), np.nan)
    dem = np.where(valid, observation.dem, np.nan)
    precipitation = np.where(valid, observation.precipitation, np.nan)
    land_use = np.where(valid, np.clip(observation.land_use_intensity, 0.0, 1.0), np.nan)

    return replace(
        observation,
        blue_band=blue,
        green_band=green,
        red_band=red,
        nir_band=nir,
        dem=dem,
        precipitation=precipitation,
        land_use_intensity=land_use,
        qa_mask=valid,
    )


def collect_observations(bundle: ObservationBundle) -> dict[int, RasterObservation]:
    return {
        year: normalize_observation(observation)
        for year, observation in bundle.observations.items()
    }


def validate_request_window(request: AnalysisRequest) -> None:
    request.validate()
