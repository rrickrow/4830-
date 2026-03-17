from __future__ import annotations

import logging
import math
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt

from river_insight import config
from river_insight.domain.models import (
    AnalysisRequest,
    AnalysisResult,
    ProviderHealth,
    RunManifest,
    StageRecord,
)
from river_insight.labels import STAGE_LABELS
from river_insight.pipeline.centerline import (
    CenterlineExtractionResult,
    compute_migration_metrics,
    compute_slope_mean,
    extract_centerline_features,
)
from river_insight.pipeline.drivers import build_regression_frame, run_ols
from river_insight.pipeline.hydrology import compute_runoff_potential_index
from river_insight.pipeline.indices import compute_ndvi, compute_ndwi, derive_fvc_series
from river_insight.pipeline.preprocess import collect_observations, validate_request_window
from river_insight.pipeline.quality import build_quality_report
from river_insight.pipeline.segments import build_response_zones, compute_segment_metrics
from river_insight.pipeline.vegetation import add_fvc_deltas, compute_buffer_stats
from river_insight.pipeline.water import compute_water_area_km2, extract_water_mask
from river_insight.providers.base import RemoteSensingProvider
from river_insight.providers.demo_provider import DemoProvider
from river_insight.providers.public_stac_provider import PublicStacProvider
from river_insight.services.export_service import ExportService
from river_insight.services.report_service import ReportService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisService:
    STAGE_SEQUENCE = (
        "provider_check",
        "data_prepare",
        "hydro_extract",
        "vegetation_analysis",
        "driver_analysis",
        "model_analysis",
        "export",
        "report",
    )

    def __init__(
        self,
        app_config: config.AppConfig | None = None,
        export_service: ExportService | None = None,
        report_service: ReportService | None = None,
    ) -> None:
        self.app_config = app_config or config.load_app_config()
        self.export_service = export_service or ExportService(self.app_config)
        self.report_service = report_service or ReportService()

    def build_default_request(self) -> AnalysisRequest:
        return AnalysisRequest(
            study_area=config.ALLOWED_STUDY_AREAS[0],
            start_year=config.DEFAULT_START_YEAR,
            end_year=config.DEFAULT_END_YEAR,
            year_step=config.DEFAULT_YEAR_STEP,
            provider=self.app_config.default_provider,
            include_report=config.DEFAULT_INCLUDE_REPORT,
            buffer_distances_m=self.app_config.default_buffer_distances_m,
            season_months=self.app_config.season_months,
            composite_strategy=self.app_config.composite_strategy,
            use_cache=self.app_config.use_cache,
            allow_demo_fallback=self.app_config.allow_demo_fallback,
        )

    def resolve_provider(self, provider_name: str) -> RemoteSensingProvider:
        if provider_name == "demo":
            return DemoProvider()
        if provider_name == "public_stac":
            return PublicStacProvider(app_config=self.app_config)
        raise ValueError(f"未知数据源: {provider_name}")

    def doctor(self, provider_name: str = "public_stac", study_area: str = "songhua") -> dict[str, Any]:
        request = replace(self.build_default_request(), provider=provider_name, study_area=study_area)
        provider = self.resolve_provider(provider_name)
        health = provider.health_check(request)
        output_root = self.export_service.output_root
        output_root.mkdir(parents=True, exist_ok=True)
        self.app_config.cache_root.mkdir(parents=True, exist_ok=True)
        writable = output_root.exists() and output_root.is_dir()
        cache_writable = self.app_config.cache_root.exists() and self.app_config.cache_root.is_dir()
        return {
            "provider_health": health.to_dict(),
            "config": {
                "output_root": str(output_root.resolve()),
                "cache_root": str(self.app_config.cache_root.resolve()),
                "aoi_path": str(self.app_config.aoi_path.resolve()),
                "season_months": list(self.app_config.season_months),
                "composite_strategy": self.app_config.composite_strategy,
                "default_provider": self.app_config.default_provider,
                "stac_catalog_url": self.app_config.stac_catalog_url,
                "analysis_grid_size": self.app_config.analysis_grid_size,
            },
            "checks": {
                "output_root_writable": writable,
                "cache_root_writable": cache_writable,
                "aoi_exists": self.app_config.aoi_path.exists(),
            },
            "status": "ok" if health.status in {"ok", "warning"} and writable and cache_writable else "error",
        }

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.export_service.list_runs(limit=limit)

    def run(self, request: AnalysisRequest) -> AnalysisResult:
        request = self._hydrate_request_defaults(request)
        validate_request_window(request)

        run_id = self.export_service.generate_run_id(request.provider)
        output_dir = self.export_service.create_run_directory(run_id)
        logger = self._build_logger(run_id, output_dir)
        manifest = RunManifest(
            run_id=run_id,
            provider=request.provider,
            study_area=request.study_area,
            request_snapshot=request.to_dict(),
            stage_records=[StageRecord(stage=stage) for stage in self.STAGE_SEQUENCE],
        )
        artifacts: dict[str, Any] = {}

        log_path = output_dir / "run.log"
        manifest.upsert_artifact("run_log", log_path, "log")
        request_snapshot_path = self.export_service.write_json(
            request.to_dict(),
            output_dir,
            "request_snapshot.json",
        )
        manifest.upsert_artifact("request_snapshot_json", request_snapshot_path, "json")
        self._write_manifest(manifest, output_dir)

        try:
            provider_payload = self._run_stage(
                manifest,
                output_dir,
                logger,
                "provider_check",
                lambda warnings: self._stage_provider_check(request, warnings),
            )
            provider: RemoteSensingProvider = provider_payload["provider"]
            provider_health: ProviderHealth = provider_payload["provider_health"]
            active_request: AnalysisRequest = provider_payload["request"]
            manifest.provider = active_request.provider
            manifest.request_snapshot = active_request.to_dict()
            request_snapshot_path = self.export_service.write_json(
                active_request.to_dict(),
                output_dir,
                "request_snapshot.json",
            )
            manifest.upsert_artifact("request_snapshot_json", request_snapshot_path, "json")
            provider_health_path = self.export_service.write_json(
                provider_health.to_dict(),
                output_dir,
                "provider_health.json",
            )
            manifest.upsert_artifact("provider_health_json", provider_health_path, "json")
            self._write_manifest(manifest, output_dir)

            data_payload = self._run_stage(
                manifest,
                output_dir,
                logger,
                "data_prepare",
                lambda warnings: self._stage_data_prepare(active_request, provider, warnings),
            )
            boundary = data_payload["boundary"]
            observations = data_payload["observations"]
            source_inventory = data_payload.get("source_inventory", {})
            preview_rgb_by_year = data_payload.get("preview_rgb_by_year", {})
            preview_bounds_wgs84 = data_payload.get("preview_bounds_wgs84")

            hydro_payload = self._run_stage(
                manifest,
                output_dir,
                logger,
                "hydro_extract",
                lambda warnings: self._stage_hydro_extract(observations, warnings),
            )

            vegetation_payload = self._run_stage(
                manifest,
                output_dir,
                logger,
                "vegetation_analysis",
                lambda warnings: self._stage_vegetation_analysis(
                    active_request,
                    observations,
                    hydro_payload["water_masks"],
                    warnings,
                ),
            )
            quality_path = self.export_service.write_json(
                vegetation_payload["quality_report"],
                output_dir,
                "quality_report.json",
            )
            manifest.upsert_artifact("quality_report_json", quality_path, "json")
            self._write_manifest(manifest, output_dir)

            driver_payload = self._run_stage(
                manifest,
                output_dir,
                logger,
                "driver_analysis",
                lambda warnings: self._stage_driver_analysis(
                    active_request,
                    provider,
                    observations,
                    hydro_payload["centerline_results"],
                    hydro_payload["water_masks"],
                    vegetation_payload["fvc_by_year"],
                    warnings,
                ),
            )

            annual_metrics = (
                hydro_payload["annual_metrics"]
                .merge(vegetation_payload["annual_metrics"], on="year", how="left")
                .merge(driver_payload["annual_metrics"], on="year", how="left")
                .sort_values("year")
                .reset_index(drop=True)
            )

            model_payload = self._run_stage(
                manifest,
                output_dir,
                logger,
                "model_analysis",
                lambda warnings: self._stage_model_analysis(
                    annual_metrics,
                    vegetation_payload["fvc_stats"],
                    driver_payload["driver_table"],
                    warnings,
                ),
            )

            export_payload = self._run_stage(
                manifest,
                output_dir,
                logger,
                "export",
                lambda warnings: self._stage_export(
                    output_dir=output_dir,
                    manifest=manifest,
                    provider_health=provider_health,
                    quality_report=vegetation_payload["quality_report"],
                    annual_metrics=annual_metrics,
                    fvc_stats=vegetation_payload["fvc_stats"],
                    centerlines_gdf=hydro_payload["centerlines_gdf"],
                    nodes_gdf=hydro_payload["nodes_gdf"],
                    segment_metrics=driver_payload["segment_metrics"],
                    response_zones_gdf=driver_payload["response_zones_gdf"],
                    regression_frame=model_payload["regression_frame"],
                    regression_summary=model_payload["regression_summary"],
                    boundary=boundary,
                    water_masks=hydro_payload["water_masks"],
                    quality_frame=vegetation_payload["quality_frame"],
                    source_inventory=source_inventory,
                    preview_rgb_by_year=preview_rgb_by_year,
                    preview_bounds_wgs84=preview_bounds_wgs84,
                    warnings=warnings,
                ),
            )
            artifacts.update(export_payload["artifacts"])

            result = AnalysisResult(
                annual_metrics=annual_metrics,
                centerlines_gdf=hydro_payload["centerlines_gdf"],
                nodes_gdf=hydro_payload["nodes_gdf"],
                fvc_stats=vegetation_payload["fvc_stats"],
                segment_metrics=driver_payload["segment_metrics"],
                response_zones_gdf=driver_payload["response_zones_gdf"],
                regression_summary=model_payload["regression_summary"],
                quality_report=vegetation_payload["quality_report"],
                provider_health=provider_health,
                manifest=manifest,
                run_id=run_id,
                boundary_gdf=boundary,
                artifacts=artifacts,
                warnings=list(manifest.warnings),
                output_dir=output_dir,
                source_inventory=source_inventory,
            )

            if active_request.include_report:
                report_payload = self._run_stage(
                    manifest,
                    output_dir,
                    logger,
                    "report",
                    lambda warnings: self._stage_report(result, active_request, warnings),
                    fatal=False,
                )
                if report_payload and report_payload.get("report_path") is not None:
                    result.artifacts["report_pdf"] = report_payload["report_path"]
                    manifest.upsert_artifact("report_pdf", report_payload["report_path"], "pdf")
            else:
                self._mark_stage_completed(
                    manifest,
                    output_dir,
                    "report",
                    warnings=["当前请求未启用 PDF 报告导出。"],
                )

            if manifest.warnings and manifest.status != "failed":
                manifest.status = "warning"
            elif manifest.status != "failed":
                manifest.status = "ok"

            manifest.completed_at = _utc_now()
            self._write_manifest(manifest, output_dir)
            result.manifest = manifest
            result.warnings = list(manifest.warnings)
            return result

        except Exception:
            manifest.status = "failed"
            manifest.completed_at = _utc_now()
            self._write_manifest(manifest, output_dir)
            raise
        finally:
            self._close_logger(logger)

    def _stage_provider_check(
        self,
        request: AnalysisRequest,
        warnings: list[str],
    ) -> dict[str, Any]:
        provider = self.resolve_provider(request.provider)
        provider_health = provider.health_check(request)
        if provider_health.status in {"ok", "warning"}:
            if provider_health.status == "warning":
                warnings.append(provider_health.message)
            return {"provider": provider, "provider_health": provider_health, "request": request}

        if request.provider != "demo" and request.allow_demo_fallback:
            warnings.append(
                f"{request.provider} 数据源不可用，已根据 allow_demo_fallback 切换到 demo 数据源。"
            )
            fallback_request = replace(request, provider="demo")
            fallback_provider = self.resolve_provider("demo")
            fallback_health = fallback_provider.health_check(fallback_request)
            if fallback_health.status != "ok":
                raise RuntimeError(fallback_health.message)
            return {
                "provider": fallback_provider,
                "provider_health": fallback_health,
                "request": fallback_request,
            }

        raise RuntimeError(provider_health.message)

    def _stage_data_prepare(
        self,
        request: AnalysisRequest,
        provider: RemoteSensingProvider,
        warnings: list[str],
    ) -> dict[str, Any]:
        bundle = provider.load_observation_bundle(request)
        observations = collect_observations(bundle)
        interpolated_years = [
            year for year, observation in observations.items() if observation.metadata.get("interpolated")
        ]
        if interpolated_years:
            warnings.append(f"以下年份使用了线性插值观测包: {interpolated_years}")
        return {
            "boundary": bundle.boundary_gdf,
            "observations": observations,
            "source_inventory": bundle.metadata.get("source_inventory", {}),
            "preview_rgb_by_year": bundle.metadata.get("preview_rgb_by_year", {}),
            "preview_bounds_wgs84": bundle.metadata.get("preview_bounds_wgs84"),
        }

    def _stage_hydro_extract(
        self,
        observations: dict[int, Any],
        warnings: list[str],
    ) -> dict[str, Any]:
        annual_rows: list[dict[str, Any]] = []
        centerline_frames: list[gpd.GeoDataFrame] = []
        node_frames: list[gpd.GeoDataFrame] = []
        water_masks: dict[int, np.ndarray] = {}
        centerline_results: dict[int, CenterlineExtractionResult] = {}

        previous_points = np.empty((0, 2), dtype=float)
        first_iteration = True

        for year, observation in sorted(observations.items()):
            ndwi = compute_ndwi(observation.green_band, observation.nir_band)
            water_result = extract_water_mask(ndwi)
            water_mask = water_result.mask & observation.qa_mask
            water_masks[year] = water_mask

            centerline = extract_centerline_features(
                mask=water_mask,
                bounds=observation.bounds,
                resolution_m=observation.resolution_m,
                year=year,
            )
            centerline_results[year] = centerline
            if centerline.point_count == 0:
                warnings.append(f"{year} 年未提取到有效中心线，迁移指标使用空值。")

            if first_iteration:
                delta_migration, swing_amplitude = (math.nan, math.nan)
                first_iteration = False
            else:
                migration_values = compute_migration_metrics(previous_points, centerline.point_coords_xy)
                delta_migration = migration_values[0] if migration_values[0] is not None else math.nan
                swing_amplitude = migration_values[1] if migration_values[1] is not None else math.nan
            previous_points = centerline.point_coords_xy

            centerline_frames.append(centerline.centerline_gdf)
            node_frames.append(centerline.nodes_gdf)

            annual_rows.append(
                {
                    "year": year,
                    "water_area_km2": compute_water_area_km2(water_mask, observation.resolution_m),
                    "centerline_length_km": centerline.centerline_length_km,
                    "mean_width_m": centerline.mean_width_m,
                    "delta_migration_m": delta_migration,
                    "swing_amplitude_m": swing_amplitude,
                    "water_threshold": water_result.threshold,
                    "used_fallback_threshold": bool(water_result.used_fallback),
                    "valid_pixel_ratio": float(np.mean(observation.qa_mask.astype(bool))),
                }
            )

        return {
            "annual_metrics": pd.DataFrame(annual_rows).sort_values("year").reset_index(drop=True),
            "water_masks": water_masks,
            "centerline_results": centerline_results,
            "centerlines_gdf": self._concat_geodataframes(centerline_frames, ["year", "geometry"]),
            "nodes_gdf": self._concat_geodataframes(
                node_frames, ["year", "node_type", "degree", "geometry"]
            ),
        }

    def _stage_vegetation_analysis(
        self,
        request: AnalysisRequest,
        observations: dict[int, Any],
        water_masks: dict[int, np.ndarray],
        warnings: list[str],
    ) -> dict[str, Any]:
        ndvi_by_year = {
            year: compute_ndvi(observation.nir_band, observation.red_band)
            for year, observation in observations.items()
        }
        fvc_by_year, ndvi_soil, ndvi_veg = derive_fvc_series(ndvi_by_year)
        quality_report = build_quality_report(ndvi_by_year, observations)
        if quality_report.get("issues"):
            warnings.append(f"质量检查发现 {len(quality_report['issues'])} 条告警。")

        annual_rows: list[dict[str, Any]] = []
        fvc_frames: list[pd.DataFrame] = []
        for year in request.years:
            observation = observations[year]
            ndvi = ndvi_by_year[year]
            fvc = fvc_by_year[year]
            water_mask = water_masks[year]
            fvc_frames.append(
                compute_buffer_stats(
                    year=year,
                    ndvi=ndvi,
                    fvc=fvc,
                    water_mask=water_mask,
                    resolution_m=observation.resolution_m,
                    buffer_distances_m=request.buffer_distances_m,
                )
            )
            annual_rows.append(
                {
                    "year": year,
                    "ndvi_mean": float(np.nanmean(ndvi)),
                    "fvc_mean": float(np.nanmean(fvc)),
                    "ndvi_soil": ndvi_soil,
                    "ndvi_veg": ndvi_veg,
                }
            )

        quality_frame = pd.DataFrame(quality_report["yearly_metrics"])
        fvc_stats = add_fvc_deltas(pd.concat(fvc_frames, ignore_index=True))
        return {
            "annual_metrics": pd.DataFrame(annual_rows).sort_values("year").reset_index(drop=True),
            "fvc_stats": fvc_stats,
            "ndvi_by_year": ndvi_by_year,
            "fvc_by_year": fvc_by_year,
            "quality_report": quality_report,
            "quality_frame": quality_frame,
        }

    def _stage_driver_analysis(
        self,
        request: AnalysisRequest,
        provider: RemoteSensingProvider,
        observations: dict[int, Any],
        centerline_results: dict[int, CenterlineExtractionResult],
        water_masks: dict[int, np.ndarray],
        fvc_by_year: dict[int, np.ndarray],
        warnings: list[str],
    ) -> dict[str, Any]:
        driver_bundle = provider.load_driver_bundle(request, observations)
        driver_lookup = driver_bundle.table.set_index("year")
        annual_rows: list[dict[str, Any]] = []
        segment_frames: list[gpd.GeoDataFrame] = []

        for year in request.years:
            observation = observations[year]
            driver_row = driver_lookup.loc[year] if year in driver_lookup.index else {}
            runoff_index = compute_runoff_potential_index(observation.dem, observation.resolution_m)
            annual_rows.append(
                {
                    "year": year,
                    "precipitation_mean": float(
                        driver_row.get("precipitation_mean", np.nanmean(observation.precipitation))
                    ),
                    "land_use_intensity_mean": float(
                        driver_row.get(
                            "land_use_intensity_mean",
                            np.nanmean(observation.land_use_intensity),
                        )
                    ),
                    "slope_mean": compute_slope_mean(observation.dem, observation.resolution_m),
                    "runoff_potential_index": runoff_index,
                }
            )
            segment_frames.append(
                compute_segment_metrics(
                    year=year,
                    centerlines_gdf=centerline_results[year].centerline_gdf,
                    bounds=observation.bounds,
                    resolution_m=observation.resolution_m,
                    water_mask=water_masks[year],
                    fvc=fvc_by_year[year],
                    precipitation=observation.precipitation,
                    land_use_intensity=observation.land_use_intensity,
                    segment_length_m=self.app_config.segment_length_m,
                    stat_buffer_m=float(request.buffer_distances_m[-1]),
                )
            )

        segment_metrics = self._concat_geodataframes(
            segment_frames,
            [
                "year",
                "line_id",
                "segment_index",
                "segment_length_m",
                "mean_width_m",
                "fvc_mean",
                "precipitation_mean",
                "land_use_intensity_mean",
                "midpoint_x",
                "midpoint_y",
                "geometry",
            ],
        )
        if segment_metrics.empty:
            warnings.append("未生成可用的河道分段结果。")
        response_zones = build_response_zones(segment_metrics)
        return {
            "annual_metrics": pd.DataFrame(annual_rows).sort_values("year").reset_index(drop=True),
            "driver_table": driver_bundle.table,
            "segment_metrics": segment_metrics,
            "response_zones_gdf": response_zones,
        }

    def _stage_model_analysis(
        self,
        annual_metrics: pd.DataFrame,
        fvc_stats: pd.DataFrame,
        driver_table: pd.DataFrame,
        warnings: list[str],
    ) -> dict[str, Any]:
        regression_frame = build_regression_frame(annual_metrics, fvc_stats, driver_table)
        regression_summary = run_ols(regression_frame)
        if regression_summary.get("status") != "ok":
            warnings.append(regression_summary.get("message", "回归分析未产出结果。"))
        return {
            "regression_frame": regression_frame,
            "regression_summary": regression_summary,
        }

    def _stage_export(
        self,
        output_dir: Path,
        manifest: RunManifest,
        provider_health: ProviderHealth,
        quality_report: dict[str, Any],
        annual_metrics: pd.DataFrame,
        fvc_stats: pd.DataFrame,
        centerlines_gdf: gpd.GeoDataFrame,
        nodes_gdf: gpd.GeoDataFrame,
        segment_metrics: gpd.GeoDataFrame,
        response_zones_gdf: gpd.GeoDataFrame,
        regression_frame: pd.DataFrame,
        regression_summary: dict[str, Any],
        boundary: gpd.GeoDataFrame,
        water_masks: dict[int, np.ndarray],
        quality_frame: pd.DataFrame,
        source_inventory: dict[str, Any],
        preview_rgb_by_year: dict[int, np.ndarray],
        preview_bounds_wgs84: list[float] | tuple[float, float, float, float] | None,
        warnings: list[str],
    ) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}

        artifacts["annual_metrics_csv"] = self.export_service.write_dataframe(
            annual_metrics, output_dir, "annual_metrics.csv"
        )
        artifacts["fvc_stats_csv"] = self.export_service.write_dataframe(
            fvc_stats, output_dir, "fvc_stats.csv"
        )
        artifacts["centerlines_geojson"] = self.export_service.write_geojson(
            centerlines_gdf, output_dir, "centerlines.geojson"
        )
        artifacts["nodes_geojson"] = self.export_service.write_geojson(
            nodes_gdf, output_dir, "nodes.geojson"
        )
        artifacts["segment_metrics_csv"] = self.export_service.write_dataframe(
            self._exportable_segment_metrics(segment_metrics),
            output_dir,
            "segment_metrics.csv",
        )
        artifacts["response_zones_geojson"] = self.export_service.write_geojson(
            response_zones_gdf,
            output_dir,
            "response_zones.geojson",
        )
        artifacts["regression_samples_csv"] = self.export_service.write_dataframe(
            regression_frame, output_dir, "regression_samples.csv"
        )

        coefficients = regression_summary.get("coefficients")
        if coefficients is not None:
            artifacts["regression_coefficients_csv"] = self.export_service.write_dataframe(
                coefficients, output_dir, "regression_coefficients.csv"
            )
        correlation_matrix = regression_summary.get("correlation_matrix")
        if isinstance(correlation_matrix, pd.DataFrame) and not correlation_matrix.empty:
            artifacts["correlation_matrix_csv"] = self.export_service.write_dataframe(
                correlation_matrix.reset_index().rename(columns={"index": "metric"}),
                output_dir,
                "correlation_matrix.csv",
            )
        contributions = regression_summary.get("driver_contributions")
        if isinstance(contributions, pd.DataFrame) and not contributions.empty:
            artifacts["driver_contributions_csv"] = self.export_service.write_dataframe(
                contributions,
                output_dir,
                "driver_contributions.csv",
            )

        artifacts["regression_summary_json"] = self.export_service.write_json(
            {
                "status": regression_summary.get("status"),
                "message": regression_summary.get("message"),
                "sample_count": regression_summary.get("sample_count"),
                "r_squared": regression_summary.get("r_squared"),
                "adjusted_r_squared": regression_summary.get("adjusted_r_squared"),
            },
            output_dir,
            "regression_summary.json",
        )
        artifacts["provider_health_json"] = self.export_service.write_json(
            provider_health.to_dict(),
            output_dir,
            "provider_health.json",
        )
        artifacts["quality_report_json"] = self.export_service.write_json(
            quality_report,
            output_dir,
            "quality_report.json",
        )
        artifacts["source_inventory_json"] = self.export_service.write_json(
            source_inventory,
            output_dir,
            "source_inventory.json",
        )

        artifacts["water_masks_panel_png"] = self.export_service.save_figure(
            self._build_water_masks_panel(water_masks),
            output_dir,
            "water_masks_panel.png",
        )
        artifacts["centerline_overlay_png"] = self.export_service.save_figure(
            self._build_centerline_overlay(boundary, centerlines_gdf, nodes_gdf),
            output_dir,
            "centerline_overlay.png",
        )
        artifacts["fvc_heatmap_png"] = self.export_service.save_figure(
            self._build_fvc_heatmap(fvc_stats),
            output_dir,
            "fvc_heatmap.png",
        )
        artifacts["coupling_png"] = self.export_service.save_figure(
            self._build_coupling_figure(regression_frame),
            output_dir,
            "coupling_scatter.png",
        )
        artifacts["regression_png"] = self.export_service.save_figure(
            self._build_regression_figure(regression_summary),
            output_dir,
            "regression_coefficients.png",
        )
        artifacts["annual_metrics_png"] = self.export_service.save_figure(
            self._build_annual_metrics_figure(annual_metrics),
            output_dir,
            "annual_metrics.png",
        )
        artifacts["ndvi_quality_png"] = self.export_service.save_figure(
            self._build_quality_figure(quality_frame),
            output_dir,
            "ndvi_quality.png",
        )
        if preview_rgb_by_year:
            artifacts["true_color_panel_png"] = self.export_service.save_figure(
                self._build_true_color_panel(preview_rgb_by_year),
                output_dir,
                "true_color_panel.png",
            )
            latest_year = max(preview_rgb_by_year)
            artifacts["true_color_latest_png"] = self.export_service.save_figure(
                self._build_single_image_figure(
                    preview_rgb_by_year[latest_year],
                ),
                output_dir,
                "true_color_latest.png",
            )
        if water_masks:
            latest_water_year = max(water_masks)
            artifacts["water_mask_latest_png"] = self.export_service.save_figure(
                self._build_single_image_figure(
                    water_masks[latest_water_year].astype(float),
                    cmap="Blues",
                ),
                output_dir,
                "water_mask_latest.png",
            )

        if manifest.warnings or warnings:
            merged_warnings = list(dict.fromkeys([*manifest.warnings, *warnings]))
            manifest.warnings = merged_warnings
            artifacts["warnings_txt"] = self.export_service.write_text(
                "\n".join(merged_warnings),
                output_dir,
                "warnings.txt",
            )

        for key, path in artifacts.items():
            if isinstance(path, Path):
                manifest.upsert_artifact(key, path, path.suffix.lstrip(".") or "file")
        self._write_manifest(manifest, output_dir)
        return {
            "artifacts": artifacts,
            "preview_bounds_wgs84": preview_bounds_wgs84,
        }

    def _stage_report(
        self,
        result: AnalysisResult,
        request: AnalysisRequest,
        warnings: list[str],
    ) -> dict[str, Any]:
        report_path = self.report_service.build_pdf(result, request)
        return {"report_path": report_path}

    def _run_stage(
        self,
        manifest: RunManifest,
        output_dir: Path,
        logger: logging.Logger,
        stage_name: str,
        func: Callable[[list[str]], Any],
        fatal: bool = True,
    ) -> Any:
        record = manifest.ensure_stage(stage_name)
        record.status = "running"
        record.started_at = _utc_now()
        self._write_manifest(manifest, output_dir)

        stage_warnings: list[str] = []
        started = time.perf_counter()
        try:
            payload = func(stage_warnings)
        except Exception as exc:
            logger.exception("阶段失败: %s", stage_name)
            record.status = "failed"
            record.error_summary = str(exc)
            record.warnings.extend(stage_warnings)
            manifest.warnings.extend(stage_warnings)
            if fatal:
                raise
            manifest.warnings.append(f"{STAGE_LABELS.get(stage_name, stage_name)}失败: {exc}")
            payload = None
        else:
            record.status = "warning" if stage_warnings else "ok"
            record.warnings.extend(stage_warnings)
            manifest.warnings.extend(stage_warnings)
        finally:
            record.completed_at = _utc_now()
            record.duration_seconds = time.perf_counter() - started
            self._write_manifest(manifest, output_dir)
        return payload

    def _mark_stage_completed(
        self,
        manifest: RunManifest,
        output_dir: Path,
        stage_name: str,
        warnings: list[str] | None = None,
    ) -> None:
        record = manifest.ensure_stage(stage_name)
        now = _utc_now()
        record.status = "warning" if warnings else "ok"
        record.started_at = now
        record.completed_at = now
        record.duration_seconds = 0.0
        if warnings:
            record.warnings.extend(warnings)
        self._write_manifest(manifest, output_dir)

    def _write_manifest(self, manifest: RunManifest, output_dir: Path) -> None:
        manifest_path = self.export_service.write_json(manifest.to_dict(), output_dir, "manifest.json")
        manifest.upsert_artifact("manifest_json", manifest_path, "json")

    def _build_logger(self, run_id: str, output_dir: Path) -> logging.Logger:
        logger = logging.getLogger(f"river_insight.run.{run_id}")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()
        logger.propagate = False
        handler = logging.FileHandler(output_dir / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.info("初始化运行目录: %s", output_dir)
        return logger

    def _close_logger(self, logger: logging.Logger) -> None:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    def _hydrate_request_defaults(self, request: AnalysisRequest) -> AnalysisRequest:
        return replace(
            request,
            buffer_distances_m=request.buffer_distances_m or self.app_config.default_buffer_distances_m,
            season_months=request.season_months or self.app_config.season_months,
            composite_strategy=request.composite_strategy or self.app_config.composite_strategy,
        )

    @staticmethod
    def _concat_geodataframes(
        frames: list[gpd.GeoDataFrame],
        columns: list[str],
    ) -> gpd.GeoDataFrame:
        non_empty = [frame for frame in frames if frame is not None and not frame.empty]
        if not non_empty:
            return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=config.MAP_CRS)
        merged = pd.concat(non_empty, ignore_index=True)
        return gpd.GeoDataFrame(merged, geometry="geometry", crs=config.MAP_CRS)

    @staticmethod
    def _exportable_segment_metrics(segment_metrics: gpd.GeoDataFrame) -> pd.DataFrame:
        if segment_metrics.empty:
            return pd.DataFrame(columns=[*segment_metrics.columns, "geometry_wkt"])
        export_frame = segment_metrics.copy()
        export_frame["geometry_wkt"] = export_frame.geometry.to_wkt()
        return pd.DataFrame(export_frame.drop(columns="geometry"))

    @staticmethod
    def _build_water_masks_panel(water_masks: dict[int, np.ndarray]) -> plt.Figure:
        years = list(water_masks)
        columns = 2
        rows = max(1, math.ceil(len(years) / columns))
        fig, axes = plt.subplots(rows, columns, figsize=(10, rows * 3.8))
        axes_array = np.atleast_1d(axes).ravel()

        for axis, year in zip(axes_array, years):
            axis.imshow(water_masks[year], cmap="Blues")
            axis.set_title(f"{year} 年水体掩膜", fontsize=10)
            axis.set_xticks([])
            axis.set_yticks([])

        for axis in axes_array[len(years) :]:
            axis.axis("off")

        fig.tight_layout()
        return fig

    @staticmethod
    def _build_true_color_panel(preview_rgb_by_year: dict[int, np.ndarray]) -> plt.Figure:
        years = list(preview_rgb_by_year)
        columns = 2
        rows = max(1, math.ceil(len(years) / columns))
        fig, axes = plt.subplots(rows, columns, figsize=(10, rows * 3.8))
        axes_array = np.atleast_1d(axes).ravel()

        for axis, year in zip(axes_array, years):
            axis.imshow(preview_rgb_by_year[year])
            axis.set_title(f"{year} 真彩色合成", fontsize=10)
            axis.set_xticks([])
            axis.set_yticks([])

        for axis in axes_array[len(years) :]:
            axis.axis("off")

        fig.tight_layout()
        return fig

    @staticmethod
    def _build_single_image_figure(
        image: np.ndarray,
        title: str | None = None,
        cmap: str | None = None,
    ) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(6.4, 6.0))
        if image.ndim == 2:
            ax.imshow(image, cmap=cmap)
        else:
            ax.imshow(image)
        if title:
            ax.set_title(title)
        ax.axis("off")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        return fig

    @staticmethod
    def _build_centerline_overlay(
        boundary: gpd.GeoDataFrame,
        centerlines_gdf: gpd.GeoDataFrame,
        nodes_gdf: gpd.GeoDataFrame,
    ) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(8.4, 6.2))
        boundary.boundary.plot(ax=ax, color="#2c3e50", linewidth=1.4)
        if not centerlines_gdf.empty:
            centerlines_gdf.plot(ax=ax, column="year", cmap="viridis", linewidth=1.1, legend=True)
        if not nodes_gdf.empty:
            nodes_gdf.plot(ax=ax, color="#c0392b", markersize=10, alpha=0.8)
        ax.set_title("河道中心线与节点分布")
        ax.set_axis_off()
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_fvc_heatmap(fvc_stats: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(8.4, 4.6))
        if fvc_stats.empty:
            ax.text(0.5, 0.5, "无植被统计结果", ha="center", va="center")
            ax.axis("off")
            return fig

        pivot = (
            fvc_stats.pivot(index="buffer_label", columns="year", values="fvc_mean")
            .sort_index(ascending=False)
            .fillna(0.0)
        )
        image = ax.imshow(pivot.values, cmap="YlGn", aspect="auto")
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index)
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns)
        ax.set_title("缓冲带 FVC 热力图")
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_coupling_figure(regression_frame: pd.DataFrame) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6))
        if regression_frame.empty:
            for axis in axes:
                axis.text(0.5, 0.5, "样本不足", ha="center", va="center")
                axis.axis("off")
            return fig

        axes[0].scatter(regression_frame["delta_width"], regression_frame["delta_fvc"], c="#1f77b4")
        axes[0].set_title("河宽变化 vs FVC 变化")
        axes[0].set_xlabel("delta_width")
        axes[0].set_ylabel("delta_fvc")

        axes[1].scatter(
            regression_frame["delta_migration"],
            regression_frame["delta_fvc"],
            c="#ff7f0e",
        )
        axes[1].set_title("迁移量 vs FVC 变化")
        axes[1].set_xlabel("delta_migration")
        axes[1].set_ylabel("delta_fvc")
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_regression_figure(regression_summary: dict[str, Any]) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(8.4, 4.8))
        coefficients = regression_summary.get("coefficients")
        if coefficients is None or coefficients.empty:
            ax.text(
                0.5,
                0.5,
                regression_summary.get("message", "无回归结果"),
                ha="center",
                va="center",
            )
            ax.axis("off")
            return fig

        ordered = coefficients.sort_values("coefficient")
        colors = ["#2ecc71" if value >= 0 else "#e74c3c" for value in ordered["coefficient"]]
        ax.barh(ordered["term"], ordered["coefficient"], color=colors)
        ax.axvline(0.0, color="#2c3e50", linewidth=1)
        ax.set_title("标准化回归系数")
        ax.set_xlabel("coefficient")
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_annual_metrics_figure(annual_metrics: pd.DataFrame) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
        axes[0].plot(annual_metrics["year"], annual_metrics["water_area_km2"], marker="o")
        axes[0].set_title("水体面积变化")
        axes[0].set_xlabel("year")
        axes[0].set_ylabel("km²")

        axes[1].plot(annual_metrics["year"], annual_metrics["mean_width_m"], marker="o", color="#16a085")
        axes[1].set_title("平均河宽变化")
        axes[1].set_xlabel("year")
        axes[1].set_ylabel("m")
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_quality_figure(quality_frame: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(8.4, 4.2))
        if quality_frame.empty:
            ax.text(0.5, 0.5, "无质量检查结果", ha="center", va="center")
            ax.axis("off")
            return fig

        ax.plot(quality_frame["year"], quality_frame["ndvi_mean"], marker="o", color="#2c7fb8")
        anomalies = quality_frame[quality_frame["is_anomaly"]]
        if not anomalies.empty:
            ax.scatter(anomalies["year"], anomalies["ndvi_mean"], color="#d7301f", label="异常年份")
            ax.legend()
        ax.set_title("年度 NDVI 质量曲线")
        ax.set_xlabel("year")
        ax.set_ylabel("ndvi_mean")
        fig.tight_layout()
        return fig
