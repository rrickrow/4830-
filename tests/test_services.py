from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from river_insight.domain.models import (
    AnalysisRequest,
    AnalysisResult,
    ObservationBundle,
    ProviderHealth,
    RasterObservation,
    RunManifest,
    StageRecord,
)
from river_insight.pipeline.drivers import run_ols
from river_insight.providers.aoi import get_study_area_boundary
from river_insight.providers.public_stac_provider import PublicStacProvider
from river_insight.services.analysis_service import AnalysisService
from river_insight.services.export_service import ExportService
from river_insight.services.report_service import ReportService


def test_run_ols_returns_required_fields() -> None:
    frame = pd.DataFrame(
        {
            "delta_fvc": [0.1, 0.12, 0.08, 0.15, 0.09, 0.11, 0.13, 0.14],
            "delta_width": [1, 2, 1.5, 3, 2.4, 2.2, 2.8, 3.1],
            "delta_migration": [2, 4, 3, 5, 4.2, 4.4, 4.8, 5.2],
            "precipitation_mean": [680, 700, 695, 720, 710, 705, 715, 725],
            "land_use_intensity_mean": [0.3, 0.35, 0.32, 0.36, 0.34, 0.33, 0.37, 0.38],
            "slope_mean": [0.8, 0.75, 0.78, 0.7, 0.73, 0.74, 0.71, 0.69],
            "runoff_potential_index": [0.42, 0.41, 0.44, 0.46, 0.45, 0.43, 0.44, 0.47],
        }
    )

    summary = run_ols(frame)

    assert summary["status"] == "ok"
    assert "r_squared" in summary
    assert "adjusted_r_squared" in summary
    assert not summary["coefficients"].empty
    assert not summary["driver_contributions"].empty


def test_report_service_builds_pdf(tmp_path: Path) -> None:
    manifest = RunManifest(
        run_id="test-run",
        provider="demo",
        study_area="songhua",
        stage_records=[StageRecord(stage="export", status="ok")],
    )
    result = AnalysisResult(
        annual_metrics=pd.DataFrame({"year": [1995], "water_area_km2": [1.0]}),
        centerlines_gdf=gpd.GeoDataFrame(
            [{"year": 1995, "geometry": LineString([(0, 0), (1, 1)])}],
            geometry="geometry",
            crs="EPSG:3857",
        ),
        nodes_gdf=gpd.GeoDataFrame(
            [{"year": 1995, "node_type": "endpoint", "degree": 1, "geometry": Point(0, 0)}],
            geometry="geometry",
            crs="EPSG:3857",
        ),
        fvc_stats=pd.DataFrame({"year": [1995], "buffer_label": ["0-300m"], "fvc_mean": [0.5]}),
        segment_metrics=pd.DataFrame(),
        response_zones_gdf=gpd.GeoDataFrame(geometry=[], crs="EPSG:3857"),
        regression_summary={
            "status": "skipped",
            "message": "样本不足",
            "sample_count": 0,
            "coefficients": pd.DataFrame(),
            "r_squared": None,
            "adjusted_r_squared": None,
        },
        quality_report={"summary": "正常", "issues": [], "yearly_metrics": []},
        provider_health=ProviderHealth(provider_name="demo", status="ok", message="ok"),
        manifest=manifest,
        run_id="test-run",
        artifacts={},
        warnings=[],
        output_dir=tmp_path,
        source_inventory={},
    )
    request = AnalysisRequest(
        study_area="songhua",
        start_year=1995,
        end_year=1995,
        year_step=10,
        provider="demo",
        include_report=True,
    )

    path = ReportService().build_pdf(result, request)

    assert path.exists()
    assert path.stat().st_size > 0


def test_public_stac_provider_health_with_stub() -> None:
    class FakeSearch:
        def __init__(self, items):
            self._items = items

        def items(self):
            return iter(self._items)

    class FakeCatalog:
        def __init__(self, mapping):
            self.mapping = mapping

        def search(self, collections, bbox=None, datetime=None, max_items=None):
            return FakeSearch(self.mapping.get(collections[0], []))

    def item(item_id: str, collection: str) -> SimpleNamespace:
        if collection == "landsat-c2-l2":
            assets = {"green": SimpleNamespace(href=f"https://example.com/{item_id}/green.tif")}
            properties = {"eo:cloud_cover": 10.0, "landsat:wrs_path": 118, "landsat:wrs_row": "031"}
        elif collection == "cop-dem-glo-30":
            assets = {"data": SimpleNamespace(href=f"https://example.com/{item_id}/dem.tif")}
            properties = {}
        else:
            assets = {"lccs_class": SimpleNamespace(href=f"https://example.com/{item_id}/lc.tif")}
            properties = {}
        return SimpleNamespace(id=item_id, assets=assets, properties=properties)

    catalog = FakeCatalog(
        {
            "landsat-c2-l2": [item("landsat-1", "landsat-c2-l2")],
            "cop-dem-glo-30": [item("dem-1", "cop-dem-glo-30")],
            "esa-cci-lc": [item("lc-1", "esa-cci-lc")],
        }
    )
    provider = PublicStacProvider(
        catalog=catalog,
        item_signer=lambda value: value,
        url_exists=lambda url: "example.com" in url or "CHIRPS-2.0" in url,
    )
    request = AnalysisRequest(
        study_area="songhua",
        start_year=1995,
        end_year=1995,
        year_step=10,
        provider="public_stac",
        include_report=False,
    )

    health = provider.health_check(request)

    assert health.status in {"ok", "warning"}
    assert health.details["catalog_url"]
    assert health.details["sample_item_ids"]["landsat"]


def test_full_analysis_pipeline_outputs_artifacts(tmp_path: Path) -> None:
    service = AnalysisService(export_service=ExportService(output_root=tmp_path))
    request = AnalysisRequest(
        study_area="songhua",
        start_year=1995,
        end_year=2025,
        year_step=10,
        provider="demo",
        include_report=True,
    )

    result = service.run(request)

    assert not result.annual_metrics.empty
    assert result.output_dir is not None
    assert result.output_dir.exists()
    assert result.run_id
    assert "annual_metrics_csv" in result.artifacts
    assert "segment_metrics_csv" in result.artifacts
    assert "response_zones_geojson" in result.artifacts
    assert "provider_health_json" in result.artifacts
    assert "quality_report_json" in result.artifacts
    assert "source_inventory_json" in result.artifacts
    assert "true_color_panel_png" in result.artifacts
    assert "report_pdf" in result.artifacts
    assert Path(result.artifacts["report_pdf"]).exists()
    assert (result.output_dir / "manifest.json").exists()
    assert result.manifest.status in {"ok", "warning"}


def test_stubbed_public_stac_run_exports_new_artifacts(tmp_path: Path) -> None:
    class StubPublicStacProvider:
        provider_name = "public_stac"

        def health_check(self, request: AnalysisRequest) -> ProviderHealth:
            return ProviderHealth(
                provider_name="public_stac",
                status="ok",
                message="ok",
                available_years=request.years,
            )

        def load_observation_bundle(self, request: AnalysisRequest) -> ObservationBundle:
            boundary = get_study_area_boundary(request.study_area)
            observations: dict[int, RasterObservation] = {}
            preview_rgb_by_year: dict[int, object] = {}
            source_inventory = {
                "provider": "public_stac",
                "preview_bounds_wgs84": list(boundary.to_crs("EPSG:4326").total_bounds),
                "years": {},
            }
            for year in request.years:
                obs = _build_stub_observation(year, tuple(float(v) for v in boundary.total_bounds))
                observations[year] = obs
                preview_rgb_by_year[year] = np.dstack([obs.red_band, obs.green_band, obs.blue_band])
                source_inventory["years"][str(year)] = {
                    "optical": {"collections": ["landsat-c2-l2"], "item_ids": [f"stub-{year}"]},
                    "landcover": {"collection": "esa-cci-lc", "source_year": year if year <= 2020 else 2021},
                    "precipitation": {"version": "v2"},
                    "interpolated": False,
                }
            return ObservationBundle(
                provider_name="public_stac",
                study_area=request.study_area,
                boundary_gdf=boundary,
                observations=observations,
                metadata={
                    "source_inventory": source_inventory,
                    "preview_rgb_by_year": preview_rgb_by_year,
                    "preview_bounds_wgs84": list(boundary.to_crs("EPSG:4326").total_bounds),
                },
            )

        def load_driver_bundle(self, request: AnalysisRequest, observations: dict[int, RasterObservation]):
            rows = []
            for year, observation in observations.items():
                rows.append(
                    {
                        "year": year,
                        "precipitation_mean": float(observation.precipitation.mean()),
                        "land_use_intensity_mean": float(observation.land_use_intensity.mean()),
                    }
                )
            return SimpleNamespace(provider_name="public_stac", table=pd.DataFrame(rows), metadata={})

    def resolve_provider(self, provider_name: str):
        if provider_name == "public_stac":
            return StubPublicStacProvider()
        return AnalysisService.resolve_provider(self, provider_name)

    service = AnalysisService(export_service=ExportService(output_root=tmp_path))
    service.resolve_provider = resolve_provider.__get__(service, AnalysisService)
    request = AnalysisRequest(
        study_area="songhua",
        start_year=1995,
        end_year=2025,
        year_step=10,
        provider="public_stac",
        include_report=False,
    )

    result = service.run(request)

    assert result.source_inventory["provider"] == "public_stac"
    assert "source_inventory_json" in result.artifacts
    assert "true_color_panel_png" in result.artifacts
    assert "true_color_latest_png" in result.artifacts


def test_cli_doctor_and_list_runs(tmp_path: Path) -> None:
    service = AnalysisService(export_service=ExportService(output_root=tmp_path))
    request = AnalysisRequest(
        study_area="songhua",
        start_year=1995,
        end_year=1995,
        year_step=10,
        provider="demo",
        include_report=False,
    )
    service.run(request)

    doctor = subprocess.run(
        [sys.executable, "-m", "river_insight.cli", "doctor", "--provider", "demo"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    list_runs = subprocess.run(
        [sys.executable, "-m", "river_insight.cli", "list-runs", "--limit", "5"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert doctor.returncode == 0
    assert "\"status\": \"ok\"" in doctor.stdout
    assert list_runs.returncode == 0


def _build_stub_observation(year: int, bounds: tuple[float, float, float, float]) -> RasterObservation:
    size = 32
    values = np.linspace(0.0, 1.0, size)
    xx, yy = np.meshgrid(values, values)
    water_mask = np.abs(yy - (0.35 + (year - 1995) * 0.002)) < 0.06
    blue = np.where(water_mask, 0.18, 0.14 + (0.04 * xx))
    green = np.where(water_mask, 0.16, 0.22 + (0.10 * yy))
    red = np.where(water_mask, 0.07, 0.18 + (0.08 * (1.0 - yy)))
    nir = np.where(water_mask, 0.03, 0.42 + (0.18 * yy))
    qa_mask = np.ones((size, size), dtype=bool)
    return RasterObservation(
        year=year,
        bounds=bounds,
        resolution_m=30.0,
        blue_band=blue,
        green_band=green,
        red_band=red,
        nir_band=nir,
        dem=110.0 + (30.0 * (1.0 - yy)),
        precipitation=np.full((size, size), 700.0 + (year - 1995)),
        land_use_intensity=np.full((size, size), 0.35),
        qa_mask=qa_mask,
        metadata={"provider": "public_stac"},
    )
