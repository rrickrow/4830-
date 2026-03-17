from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from river_insight import config


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


@dataclass(slots=True)
class RasterObservation:
    year: int
    bounds: tuple[float, float, float, float]
    resolution_m: float
    green_band: np.ndarray
    nir_band: np.ndarray
    red_band: np.ndarray
    dem: np.ndarray
    precipitation: np.ndarray
    land_use_intensity: np.ndarray
    qa_mask: np.ndarray
    blue_band: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ObservationBundle:
    provider_name: str
    study_area: str
    boundary_gdf: gpd.GeoDataFrame
    observations: dict[int, RasterObservation]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DriverBundle:
    provider_name: str
    table: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderHealth:
    provider_name: str
    status: str
    message: str
    available_years: list[int] = field(default_factory=list)
    checked_at: datetime = field(default_factory=_utc_now)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checked_at"] = _iso(self.checked_at)
        return payload


@dataclass(slots=True)
class QualityIssue:
    severity: str
    year: int | None
    metric: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StageRecord:
    stage: str
    status: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)
    error_summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "duration_seconds": self.duration_seconds,
            "warnings": list(self.warnings),
            "error_summary": self.error_summary,
        }


@dataclass(slots=True)
class ArtifactRecord:
    key: str
    path: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunManifest:
    run_id: str
    provider: str
    study_area: str
    status: str = "running"
    started_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None
    request_snapshot: dict[str, Any] = field(default_factory=dict)
    stage_records: list[StageRecord] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def stage_map(self) -> dict[str, StageRecord]:
        return {record.stage: record for record in self.stage_records}

    def ensure_stage(self, stage: str) -> StageRecord:
        records = self.stage_map()
        if stage in records:
            return records[stage]
        record = StageRecord(stage=stage)
        self.stage_records.append(record)
        return record

    def upsert_artifact(self, key: str, path: Path, kind: str) -> None:
        normalized = str(path.resolve())
        for artifact in self.artifacts:
            if artifact.key == key:
                artifact.path = normalized
                artifact.kind = kind
                return
        self.artifacts.append(ArtifactRecord(key=key, path=normalized, kind=kind))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "provider": self.provider,
            "study_area": self.study_area,
            "status": self.status,
            "started_at": _iso(self.started_at),
            "completed_at": _iso(self.completed_at),
            "request_snapshot": self.request_snapshot,
            "stage_records": [record.to_dict() for record in self.stage_records],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class SegmentResponseRecord:
    year: int
    period_label: str | None
    line_id: int
    segment_index: int
    response_class: str
    delta_fvc: float | None
    delta_migration: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisRequest:
    study_area: str
    start_year: int
    end_year: int
    year_step: int
    provider: str = config.DEFAULT_PROVIDER
    include_report: bool = config.DEFAULT_INCLUDE_REPORT
    buffer_distances_m: tuple[int, ...] = config.DEFAULT_BUFFER_DISTANCES_M
    season_months: tuple[int, int] = config.DEFAULT_SEASON_MONTHS
    composite_strategy: str = config.DEFAULT_COMPOSITE_STRATEGY
    use_cache: bool = config.DEFAULT_USE_CACHE
    allow_demo_fallback: bool = config.DEFAULT_ALLOW_DEMO_FALLBACK

    def validate(self) -> None:
        if self.study_area not in config.ALLOWED_STUDY_AREAS:
            raise ValueError(f"不支持的研究区: {self.study_area}")
        if self.provider not in config.ALLOWED_PROVIDERS:
            raise ValueError(f"不支持的数据源: {self.provider}")
        if self.start_year > self.end_year:
            raise ValueError("开始年份不能大于结束年份")
        if self.year_step <= 0:
            raise ValueError("年份步长必须大于 0")
        if self.start_year < config.BASE_YEARS[0] or self.end_year > config.BASE_YEARS[-1]:
            raise ValueError(
                f"当前系统支持的年份范围为 {config.BASE_YEARS[0]}-{config.BASE_YEARS[-1]}"
            )
        if not self.buffer_distances_m:
            raise ValueError("缓冲区配置不能为空")
        if tuple(sorted(self.buffer_distances_m)) != tuple(self.buffer_distances_m):
            raise ValueError("缓冲区距离必须按升序排列")
        if len(self.season_months) != 2:
            raise ValueError("生长季月份必须同时包含开始月和结束月")
        start_month, end_month = self.season_months
        if start_month < 1 or end_month > 12 or start_month > end_month:
            raise ValueError("生长季月份范围无效")
        if self.composite_strategy not in config.ALLOWED_COMPOSITE_STRATEGIES:
            raise ValueError(f"不支持的年度合成策略: {self.composite_strategy}")

    @property
    def years(self) -> list[int]:
        values = list(range(self.start_year, self.end_year + 1, self.year_step))
        if not values:
            return [self.start_year]
        if values[-1] != self.end_year:
            values.append(self.end_year)
        return values

    def to_dict(self) -> dict[str, Any]:
        return {
            "study_area": self.study_area,
            "start_year": self.start_year,
            "end_year": self.end_year,
            "year_step": self.year_step,
            "provider": self.provider,
            "include_report": self.include_report,
            "buffer_distances_m": list(self.buffer_distances_m),
            "season_months": list(self.season_months),
            "composite_strategy": self.composite_strategy,
            "use_cache": self.use_cache,
            "allow_demo_fallback": self.allow_demo_fallback,
        }


@dataclass(slots=True)
class AnalysisResult:
    annual_metrics: pd.DataFrame
    centerlines_gdf: gpd.GeoDataFrame
    nodes_gdf: gpd.GeoDataFrame
    fvc_stats: pd.DataFrame
    segment_metrics: pd.DataFrame
    response_zones_gdf: gpd.GeoDataFrame
    regression_summary: dict[str, Any]
    quality_report: dict[str, Any]
    provider_health: ProviderHealth
    manifest: RunManifest
    run_id: str
    boundary_gdf: gpd.GeoDataFrame | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    output_dir: Path | None = None
    source_inventory: dict[str, Any] = field(default_factory=dict)
