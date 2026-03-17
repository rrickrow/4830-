from __future__ import annotations

from typing import Protocol

from river_insight.domain.models import (
    AnalysisRequest,
    DriverBundle,
    ObservationBundle,
    ProviderHealth,
    RasterObservation,
)


class RemoteSensingProvider(Protocol):
    provider_name: str

    def health_check(self, request: AnalysisRequest) -> ProviderHealth:
        ...

    def load_observation_bundle(self, request: AnalysisRequest) -> ObservationBundle:
        ...

    def load_driver_bundle(
        self,
        request: AnalysisRequest,
        observations: dict[int, RasterObservation],
    ) -> DriverBundle:
        ...
