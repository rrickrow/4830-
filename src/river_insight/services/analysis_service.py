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
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

matplotlib.use("Agg")

# Register the Noto Sans CJK font for proper Chinese character rendering
try:
    import matplotlib.font_manager as _fm
    for _fp in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if Path(_fp).exists():
            _fm.fontManager.addfont(_fp)
            break
except Exception:
    pass

matplotlib.rcParams["font.sans-serif"] = [
    "Noto Sans CJK JP",
    "Noto Sans CJK SC",
    "Microsoft YaHei",
    "SimHei",
    "WenQuanYi Micro Hei",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False
matplotlib.rcParams["figure.dpi"] = 100

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
        artifacts["precipitation_trend_png"] = self.export_service.save_figure(
            self._build_precipitation_figure(annual_metrics),
            output_dir,
            "precipitation_trend.png",
        )
        artifacts["response_summary_png"] = self.export_service.save_figure(
            self._build_response_summary_figure(response_zones_gdf),
            output_dir,
            "response_summary.png",
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
        fig, axes = plt.subplots(rows, columns, figsize=(11, rows * 4.2))
        axes_array = np.atleast_1d(axes).ravel()

        # Custom colormap: off-white land → river blue water
        water_cmap = mcolors.LinearSegmentedColormap.from_list(
            "river_water", ["#e8f4f8", "#2196f3", "#0d47a1"]
        )

        for axis, year in zip(axes_array, years):
            mask = water_masks[year].astype(float)
            water_area_km2 = float(np.sum(water_masks[year])) * (30.0 ** 2) / 1e6
            im = axis.imshow(mask, cmap=water_cmap, vmin=0, vmax=1, interpolation="nearest")
            axis.set_title(
                f"{year} 年水体掩膜\n面积: {water_area_km2:.2f} km²",
                fontsize=9,
                pad=4,
            )
            axis.set_xticks([])
            axis.set_yticks([])
            axis.spines[:].set_color("#cccccc")
            # Add a small colorbar
            cbar = fig.colorbar(im, ax=axis, fraction=0.04, pad=0.02, ticks=[0, 1])
            cbar.set_ticklabels(["陆地", "水体"], fontsize=7)

        for axis in axes_array[len(years) :]:
            axis.axis("off")

        fig.suptitle("年度水体掩膜提取结果（NDWI Otsu 阈值法）", fontsize=11, y=1.01)
        fig.tight_layout(pad=1.2)
        return fig

    @staticmethod
    def _build_true_color_panel(preview_rgb_by_year: dict[int, np.ndarray]) -> plt.Figure:
        years = list(preview_rgb_by_year)
        columns = 2
        rows = max(1, math.ceil(len(years) / columns))
        fig, axes = plt.subplots(rows, columns, figsize=(11, rows * 4.2))
        axes_array = np.atleast_1d(axes).ravel()

        for axis, year in zip(axes_array, years):
            rgb = preview_rgb_by_year[year].astype(float)
            # Percentile contrast stretch (2%–98%) for more vivid display
            if rgb.ndim == 3 and rgb.shape[2] >= 3:
                stretched = np.zeros_like(rgb)
                for ch in range(3):
                    channel = rgb[:, :, ch]
                    p2, p98 = np.percentile(channel, (2, 98))
                    # Fall back to 1.0 range when the channel is nearly constant
                    denom = p98 - p2 if p98 > p2 else 1.0
                    stretched[:, :, ch] = np.clip((channel - p2) / denom, 0.0, 1.0)
                display = stretched[:, :, :3]
            else:
                display = np.clip(rgb, 0.0, 1.0)
            axis.imshow(display, interpolation="bilinear")
            axis.set_title(f"{year} 年真彩色合成 (R-G-B)", fontsize=9, pad=4)
            axis.set_xticks([])
            axis.set_yticks([])
            axis.spines[:].set_color("#cccccc")

        for axis in axes_array[len(years) :]:
            axis.axis("off")

        fig.suptitle("年度真彩色合成影像（2%-98% 拉伸增强）", fontsize=11, y=1.01)
        fig.tight_layout(pad=1.2)
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
        fig, ax = plt.subplots(figsize=(9.0, 6.8))
        ax.set_facecolor("#e8f4f8")
        boundary.boundary.plot(ax=ax, color="#34495e", linewidth=1.6, zorder=3)
        boundary.plot(ax=ax, color="#f0f4e8", alpha=0.5, zorder=1)

        year_handles: list[mpatches.Patch] = []
        if not centerlines_gdf.empty:
            years_sorted = sorted(centerlines_gdf["year"].unique())
            n_years = len(years_sorted)
            palette = plt.cm.plasma(np.linspace(0.15, 0.88, n_years))
            year_color = dict(zip(years_sorted, palette))
            for year in years_sorted:
                subset = centerlines_gdf[centerlines_gdf["year"] == year]
                color = year_color[year]
                subset.plot(ax=ax, color=color, linewidth=1.4, zorder=4)
                year_handles.append(
                    mpatches.Patch(color=color, label=str(year))
                )

        if not nodes_gdf.empty:
            endpoint_mask = nodes_gdf["node_type"] == "endpoint"
            junction_mask = nodes_gdf["node_type"] == "junction"
            if endpoint_mask.any():
                nodes_gdf[endpoint_mask].plot(
                    ax=ax, color="#e74c3c", markersize=12, alpha=0.9, zorder=5
                )
            if junction_mask.any():
                nodes_gdf[junction_mask].plot(
                    ax=ax, color="#f39c12", markersize=14, marker="^", alpha=0.9, zorder=5
                )
            endpoint_handle = mpatches.Patch(color="#e74c3c", label="端点")
            junction_handle = mpatches.Patch(color="#f39c12", label="汇流节点")
            year_handles.extend([endpoint_handle, junction_handle])

        if year_handles:
            ax.legend(handles=year_handles, loc="lower right", fontsize=7.5, framealpha=0.85)

        ax.set_title("河道中心线年际变化与节点分布", fontsize=12, pad=8)
        ax.set_xlabel("东向坐标 (m)")
        ax.set_ylabel("北向坐标 (m)")
        ax.ticklabel_format(style="sci", axis="both", scilimits=(0, 0))
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.5, color="#aaaaaa")
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_fvc_heatmap(fvc_stats: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(9.5, 5.0))
        if fvc_stats.empty:
            ax.text(0.5, 0.5, "无植被统计结果", ha="center", va="center", fontsize=12)
            ax.axis("off")
            return fig

        pivot = (
            fvc_stats.pivot(index="buffer_label", columns="year", values="fvc_mean")
            .sort_index(ascending=False)
            .fillna(0.0)
        )
        vmin = max(0.0, pivot.values.min() - 0.05)
        vmax = min(1.0, pivot.values.max() + 0.05)
        image = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto", vmin=vmin, vmax=vmax)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index, fontsize=9)
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([str(y) for y in pivot.columns], rotation=45, ha="right", fontsize=9)
        ax.set_ylabel("缓冲带")
        ax.set_xlabel("年份")
        ax.set_title("植被覆盖度(FVC)缓冲带热力图", fontsize=11, pad=8)

        # Annotate each cell with the FVC value
        for row_i, row_label in enumerate(pivot.index):
            for col_i, col_label in enumerate(pivot.columns):
                val = pivot.loc[row_label, col_label]
                text_color = "black" if 0.35 < val < 0.75 else "white"
                ax.text(col_i, row_i, f"{val:.2f}", ha="center", va="center",
                        fontsize=7.5, color=text_color, fontweight="bold")

        cbar = fig.colorbar(image, ax=ax, fraction=0.04, pad=0.04)
        cbar.set_label("FVC 均值", fontsize=9)
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_coupling_figure(regression_frame: pd.DataFrame) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.2))
        if regression_frame.empty:
            for axis in axes:
                axis.text(0.5, 0.5, "样本不足", ha="center", va="center", fontsize=12)
                axis.axis("off")
            return fig

        def _scatter_with_trend(ax: plt.Axes, x_col: str, y_col: str, title: str, xlabel: str) -> None:
            x = regression_frame[x_col].dropna().values
            y = regression_frame[y_col].dropna().values
            common = min(len(x), len(y))
            x, y = x[:common], y[:common]

            # Color points by buffer zone if available
            if "buffer_label" in regression_frame.columns:
                labels = regression_frame["buffer_label"].values[:common]
                unique_labels = list(dict.fromkeys(labels))
                palette = plt.cm.tab10(np.linspace(0, 0.5, len(unique_labels)))
                label_color = dict(zip(unique_labels, palette))
                scatter_colors = [label_color[lb] for lb in labels]
                sc = ax.scatter(x, y, c=scatter_colors, s=45, alpha=0.75, edgecolors="white", linewidths=0.5, zorder=4)
                for lbl, col in label_color.items():
                    ax.scatter([], [], c=[col], s=40, label=lbl, alpha=0.85)
                ax.legend(fontsize=7.5, loc="upper left", framealpha=0.8)
            else:
                ax.scatter(x, y, c="#1f77b4", s=45, alpha=0.75, edgecolors="white", linewidths=0.5, zorder=4)

            # Linear regression trend line
            if len(x) >= 3:
                slope, intercept, r_value, p_value, _ = scipy_stats.linregress(x, y)
                x_line = np.linspace(x.min(), x.max(), 100)
                y_line = slope * x_line + intercept
                ax.plot(x_line, y_line, color="#e74c3c", linewidth=1.8, linestyle="--", zorder=5,
                        label=f"趋势线 R²={r_value**2:.3f}")
                sig_marker = "***" if p_value < 0.001 else "**" if p_value < 0.01 else "*" if p_value < 0.05 else "ns"
                ax.text(
                    0.97, 0.04,
                    f"R²={r_value**2:.3f}  p={p_value:.3f} {sig_marker}",
                    transform=ax.transAxes,
                    ha="right", va="bottom", fontsize=8,
                    bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "edgecolor": "#cccccc", "alpha": 0.8},
                )

            ax.set_title(title, fontsize=10, pad=6)
            ax.set_xlabel(xlabel, fontsize=9)
            ax.set_ylabel("ΔFVC", fontsize=9)
            ax.axhline(0, color="#aaaaaa", linewidth=0.8, linestyle=":")
            ax.axvline(0, color="#aaaaaa", linewidth=0.8, linestyle=":")
            ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)

        _scatter_with_trend(axes[0], "delta_width", "delta_fvc", "河宽变化 vs 植被响应", "Δ河宽 (m)")
        _scatter_with_trend(axes[1], "delta_migration", "delta_fvc", "河道迁移量 vs 植被响应", "Δ迁移量 (m)")

        fig.suptitle("河道变化与植被覆盖度(FVC)耦合关系", fontsize=12, y=1.01)
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_regression_figure(regression_summary: dict[str, Any]) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(9.5, 5.4))
        coefficients = regression_summary.get("coefficients")
        if coefficients is None or (hasattr(coefficients, "empty") and coefficients.empty):
            ax.text(
                0.5,
                0.5,
                regression_summary.get("message", "无回归结果"),
                ha="center",
                va="center",
                fontsize=12,
            )
            ax.axis("off")
            return fig

        ordered = coefficients.sort_values("coefficient").reset_index(drop=True)
        # Color by significance (p_value) and direction
        def _bar_color(row: pd.Series) -> str:
            p = row.get("p_value", 1.0)
            coef = row.get("coefficient", 0.0)
            if p < 0.05:
                return "#2ecc71" if coef >= 0 else "#e74c3c"
            return "#95d5b2" if coef >= 0 else "#f4b8b8"

        colors = [_bar_color(row) for _, row in ordered.iterrows()]
        yerr_low = ordered["coefficient"] - ordered["ci_low"]
        yerr_high = ordered["ci_high"] - ordered["coefficient"]

        bars = ax.barh(
            ordered["term"],
            ordered["coefficient"],
            color=colors,
            xerr=[yerr_low, yerr_high],
            error_kw={"ecolor": "#555555", "elinewidth": 1.2, "capsize": 4},
            height=0.6,
        )

        # Significance stars
        for bar_obj, (_, row) in zip(bars, ordered.iterrows()):
            p = row.get("p_value", 1.0)
            star = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
            if star:
                coef = row["coefficient"]
                ci_offset = yerr_high.iloc[row.name] if coef >= 0 else -yerr_low.iloc[row.name]
                x_pos = coef + ci_offset
                ha = "left" if coef >= 0 else "right"
                x_text = x_pos + (0.01 if coef >= 0 else -0.01)
                ax.text(
                    x_text,
                    bar_obj.get_y() + bar_obj.get_height() / 2,
                    star,
                    va="center", ha=ha,
                    fontsize=9, color="#333333",
                )

        ax.axvline(0.0, color="#2c3e50", linewidth=1.2)
        ax.set_title("驱动因子标准化回归系数（FVC 变化量）", fontsize=11, pad=8)
        ax.set_xlabel("标准化系数", fontsize=9)

        # Legend for significance
        sig_patch = mpatches.Patch(color="#2ecc71", label="正向显著 (p<0.05)")
        neg_patch = mpatches.Patch(color="#e74c3c", label="负向显著 (p<0.05)")
        ns_patch = mpatches.Patch(color="#95d5b2", label="正向不显著")
        ax.legend(handles=[sig_patch, neg_patch, ns_patch], fontsize=7.5, loc="lower right", framealpha=0.85)
        ax.grid(True, axis="x", linestyle="--", linewidth=0.4, alpha=0.4)

        r2 = regression_summary.get("r_squared")
        adj_r2 = regression_summary.get("adjusted_r_squared")
        n = regression_summary.get("sample_count")
        if r2 is not None:
            ax.text(
                0.98, 0.98,
                f"n={n}  R²={r2:.3f}  调整R²={adj_r2:.3f}",
                transform=ax.transAxes,
                ha="right", va="top", fontsize=8,
                bbox={"boxstyle": "round,pad=0.3", "facecolor": "#f9f9f9", "edgecolor": "#cccccc"},
            )
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_annual_metrics_figure(annual_metrics: pd.DataFrame) -> plt.Figure:
        fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.0))

        def _plot_with_trend(ax: plt.Axes, years: np.ndarray, values: np.ndarray,
                             title: str, ylabel: str, color: str) -> None:
            ax.plot(years, values, marker="o", color=color, linewidth=2.0,
                    markersize=6, markeredgecolor="white", markeredgewidth=0.8,
                    zorder=4, label="年度值")
            ax.fill_between(years, values, alpha=0.15, color=color, zorder=2)
            # Trend line
            if len(years) >= 3:
                slope, intercept, r_value, p_value, _ = scipy_stats.linregress(years, values)
                trend = slope * years + intercept
                ax.plot(years, trend, linestyle="--", color="#e74c3c", linewidth=1.6,
                        zorder=5, label=f"趋势线 (斜率={slope:.3f}/yr)")
                direction = "上升" if slope > 0 else "下降"
                sig = "显著" if p_value < 0.05 else "不显著"
                ax.text(0.97, 0.03,
                        f"{direction}趋势 {sig}\nR²={r_value**2:.3f}  p={p_value:.3f}",
                        transform=ax.transAxes,
                        ha="right", va="bottom", fontsize=8,
                        bbox={"boxstyle": "round,pad=0.3", "facecolor": "white",
                              "edgecolor": "#cccccc", "alpha": 0.85})
            # Reference mean line
            mean_val = float(np.mean(values))
            ax.axhline(mean_val, color="#7f7f7f", linewidth=0.9, linestyle=":", alpha=0.8,
                       label=f"均值: {mean_val:.2f}")
            ax.set_title(title, fontsize=10, pad=6)
            ax.set_xlabel("年份", fontsize=9)
            ax.set_ylabel(ylabel, fontsize=9)
            ax.legend(fontsize=7.5, framealpha=0.85)
            ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)
            ax.set_xticks(years)
            ax.tick_params(axis="x", rotation=45)

        years = annual_metrics["year"].values.astype(float)
        _plot_with_trend(axes[0], years, annual_metrics["water_area_km2"].values,
                         "水体面积年际变化", "面积 (km²)", "#1565c0")
        _plot_with_trend(axes[1], years, annual_metrics["mean_width_m"].values,
                         "平均河宽年际变化", "河宽 (m)", "#00796b")

        fig.suptitle("水文指标年际变化趋势分析", fontsize=12, y=1.01)
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_quality_figure(quality_frame: pd.DataFrame) -> plt.Figure:
        fig, ax = plt.subplots(figsize=(9.5, 4.8))
        if quality_frame.empty:
            ax.text(0.5, 0.5, "无质量检查结果", ha="center", va="center", fontsize=12)
            ax.axis("off")
            return fig

        years = quality_frame["year"].values
        ndvi = quality_frame["ndvi_mean"].values

        ax.plot(years, ndvi, marker="o", color="#2c7fb8", linewidth=2.0,
                markersize=6, markeredgecolor="white", markeredgewidth=0.8,
                zorder=4, label="NDVI 均值")
        ax.fill_between(years, ndvi, alpha=0.12, color="#2c7fb8", zorder=2)

        # ±1σ shaded band
        mean_val = float(np.mean(ndvi))
        std_val = float(np.std(ndvi, ddof=0))
        ax.axhline(mean_val, color="#555555", linewidth=0.9, linestyle="-.", alpha=0.7,
                   label=f"均值: {mean_val:.3f}")
        ax.fill_between(years,
                        [mean_val - std_val] * len(years),
                        [mean_val + std_val] * len(years),
                        alpha=0.08, color="#2c7fb8", zorder=1, label="±1σ 范围")

        # Mark anomalies
        if "is_anomaly" in quality_frame.columns:
            anomalies = quality_frame[quality_frame["is_anomaly"]]
            if not anomalies.empty:
                ax.scatter(anomalies["year"], anomalies["ndvi_mean"],
                           color="#d7301f", s=80, zorder=6,
                           label="异常年份", edgecolors="white", linewidths=0.8)
                for _, row in anomalies.iterrows():
                    ax.annotate(
                        f"{int(row['year'])}",
                        xy=(row["year"], row["ndvi_mean"]),
                        xytext=(6, 8), textcoords="offset points",
                        fontsize=8, color="#d7301f",
                    )

        ax.set_title("年度 NDVI 均值质量曲线", fontsize=11, pad=8)
        ax.set_xlabel("年份", fontsize=9)
        ax.set_ylabel("NDVI 均值", fontsize=9)
        ax.set_xticks(years)
        ax.tick_params(axis="x", rotation=45)
        ax.legend(fontsize=8, framealpha=0.85)
        ax.grid(True, linestyle="--", linewidth=0.4, alpha=0.4)
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_precipitation_figure(annual_metrics: pd.DataFrame) -> plt.Figure:
        """Precipitation trend bar chart with 5-year rolling mean overlay."""
        fig, ax = plt.subplots(figsize=(10.0, 5.0))

        precip_col = "precipitation_mean"
        if annual_metrics.empty or precip_col not in annual_metrics.columns:
            ax.text(0.5, 0.5, "无降水数据", ha="center", va="center", fontsize=12)
            ax.axis("off")
            return fig

        years = annual_metrics["year"].values.astype(int)
        precip = annual_metrics[precip_col].values.astype(float)

        # Bar chart colored by relative precipitation
        precip_range = float(precip.max() - precip.min())
        precip_norm = (precip - precip.min()) / (precip_range + 1e-6) if precip_range > 0 else np.full_like(precip, 0.5)
        bar_colors = plt.cm.RdYlGn(0.2 + 0.6 * precip_norm)
        ax.bar(years, precip, color=bar_colors, width=max(1, (years[-1] - years[0]) / len(years) * 0.75),
               alpha=0.85, edgecolor="white", linewidth=0.5, zorder=3)

        # Rolling mean (window = min(3, n))
        if len(precip) >= 3:
            window = min(3, len(precip))
            rolling = pd.Series(precip).rolling(window, center=True, min_periods=1).mean().values
            ax.plot(years, rolling, color="#1565c0", linewidth=2.2, linestyle="-",
                    marker="o", markersize=5, markeredgecolor="white", markeredgewidth=0.8,
                    zorder=5, label=f"{window}期滑动均值")

        # Linear trend
        if len(years) >= 3:
            slope, intercept, r_value, p_value, _ = scipy_stats.linregress(years, precip)
            trend_line = slope * years + intercept
            ax.plot(years, trend_line, color="#e74c3c", linewidth=1.6, linestyle="--",
                    zorder=4, label=f"线性趋势 ({slope:+.1f} mm/yr)")
            sig = "显著" if p_value < 0.05 else "不显著"
            direction = "增加" if slope > 0 else "减少"
            ax.text(0.97, 0.97,
                    f"趋势: {direction} {abs(slope):.1f} mm/yr ({sig})\n"
                    f"R²={r_value**2:.3f}  p={p_value:.3f}",
                    transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
                    bbox={"boxstyle": "round,pad=0.4", "facecolor": "white",
                          "edgecolor": "#cccccc", "alpha": 0.85})

        # Mean reference
        mean_precip = float(np.mean(precip))
        ax.axhline(mean_precip, color="#7f7f7f", linewidth=1.0, linestyle=":",
                   label=f"均值: {mean_precip:.0f} mm")

        ax.set_title("年均降水量变化趋势（生长季）", fontsize=11, pad=8)
        ax.set_xlabel("年份", fontsize=9)
        ax.set_ylabel("降水量 (mm)", fontsize=9)
        ax.set_xticks(years)
        ax.tick_params(axis="x", rotation=45)
        ax.legend(fontsize=8, framealpha=0.85)
        ax.grid(True, axis="y", linestyle="--", linewidth=0.4, alpha=0.4)
        fig.tight_layout()
        return fig

    @staticmethod
    def _build_response_summary_figure(response_zones_gdf: gpd.GeoDataFrame) -> plt.Figure:
        """Stacked bar chart of response zone categories (recovery/stable/degradation)."""
        fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.2))

        if response_zones_gdf is None or response_zones_gdf.empty or "response_class" not in response_zones_gdf.columns:
            for ax in axes:
                ax.text(0.5, 0.5, "无响应区分类数据", ha="center", va="center", fontsize=12)
                ax.axis("off")
            return fig

        class_colors = {"recovery": "#27ae60", "stable": "#3498db", "degradation": "#e74c3c"}
        class_labels_cn = {"recovery": "恢复", "stable": "稳定", "degradation": "退化"}

        # --- Panel 1: Pie chart of overall distribution ---
        ax_pie = axes[0]
        counts = response_zones_gdf["response_class"].value_counts()
        pie_labels = [class_labels_cn.get(c, c) for c in counts.index]
        pie_colors = [class_colors.get(c, "#888888") for c in counts.index]
        wedge_props = {"edgecolor": "white", "linewidth": 1.5}
        ax_pie.pie(
            counts.values,
            labels=pie_labels,
            colors=pie_colors,
            autopct="%1.1f%%",
            startangle=90,
            wedgeprops=wedge_props,
            textprops={"fontsize": 9},
        )
        ax_pie.set_title("响应区整体分布", fontsize=10, pad=8)

        # --- Panel 2: Bar chart of FVC delta distribution by class ---
        ax_bar = axes[1]
        if "delta_fvc" in response_zones_gdf.columns:
            classes = ["recovery", "stable", "degradation"]
            medians, q25s, q75s = [], [], []
            valid_classes = []
            for cls in classes:
                subset = response_zones_gdf[response_zones_gdf["response_class"] == cls]["delta_fvc"].dropna()
                if subset.empty:
                    continue
                medians.append(float(subset.median()))
                q25s.append(float(subset.quantile(0.25)))
                q75s.append(float(subset.quantile(0.75)))
                valid_classes.append(cls)

            if valid_classes:
                x_pos = np.arange(len(valid_classes))
                bar_colors_list = [class_colors.get(c, "#888888") for c in valid_classes]
                ax_bar.bar(x_pos, medians, color=bar_colors_list, width=0.5,
                           alpha=0.85, edgecolor="white", linewidth=1.0, zorder=3)
                # Interquartile range as error bars
                yerr_low = [m - q for m, q in zip(medians, q25s)]
                yerr_high = [q - m for m, q in zip(medians, q75s)]
                ax_bar.errorbar(x_pos, medians, yerr=[yerr_low, yerr_high],
                                fmt="none", color="#333333", capsize=5, linewidth=1.5, zorder=4)
                ax_bar.set_xticks(x_pos)
                ax_bar.set_xticklabels([class_labels_cn.get(c, c) for c in valid_classes], fontsize=10)
                ax_bar.axhline(0, color="#555555", linewidth=0.9, linestyle="--", alpha=0.7)
                ax_bar.set_ylabel("ΔFVC 中位数 (IQR 误差棒)", fontsize=9)
                ax_bar.set_title("各响应类别 FVC 变化量", fontsize=10, pad=8)
                ax_bar.grid(True, axis="y", linestyle="--", linewidth=0.4, alpha=0.4)
            else:
                ax_bar.text(0.5, 0.5, "无有效分段数据", ha="center", va="center", fontsize=12)
                ax_bar.axis("off")
        else:
            ax_bar.text(0.5, 0.5, "缺少 delta_fvc 列", ha="center", va="center", fontsize=12)
            ax_bar.axis("off")

        fig.suptitle("河道缓冲带植被响应区综合分析", fontsize=12, y=1.01)
        fig.tight_layout()
        return fig
