from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from river_insight import config
from river_insight.domain.models import AnalysisRequest, RasterObservation
from river_insight.pipeline.centerline import extract_centerline_features
from river_insight.pipeline.hydrology import compute_runoff_potential_index
from river_insight.pipeline.indices import compute_fvc, compute_ndvi, compute_ndwi
from river_insight.pipeline.quality import build_quality_report
from river_insight.pipeline.segments import classify_response
from river_insight.pipeline.water import extract_water_mask
from river_insight.providers.demo_provider import DemoProvider
from river_insight.providers.public_stac_provider import PublicStacProvider


def test_index_formulas_produce_expected_values() -> None:
    green = np.array([[0.2, 0.3]])
    red = np.array([[0.15, 0.25]])
    nir = np.array([[0.6, 0.1]])

    ndwi = compute_ndwi(green, nir)
    ndvi = compute_ndvi(nir, red)
    fvc = compute_fvc(ndvi, ndvi_soil=0.1, ndvi_veg=0.9)

    assert np.isclose(ndwi[0, 0], (0.2 - 0.6) / (0.2 + 0.6 + 1e-6))
    assert np.isclose(ndvi[0, 0], (0.6 - 0.15) / (0.6 + 0.15 + 1e-6))
    assert np.all((fvc >= 0.0) & (fvc <= 1.0))


def test_min_connected_pixels_matches_plan() -> None:
    assert config.MIN_CONNECTED_PIXELS == 112


def test_y_shape_detects_junction_and_endpoints() -> None:
    mask = np.zeros((9, 9), dtype=bool)
    mask[1:6, 4] = True
    mask[5, 2:7] = True

    result = extract_centerline_features(
        mask=mask,
        bounds=(0.0, 0.0, 270.0, 270.0),
        resolution_m=30.0,
        year=2025,
    )

    junctions = result.nodes_gdf[result.nodes_gdf["node_type"] == "junction"]
    endpoints = result.nodes_gdf[result.nodes_gdf["node_type"] == "endpoint"]

    assert len(junctions) >= 1
    assert len(endpoints) >= 3


def test_otsu_fallback_is_triggered_for_flat_signal() -> None:
    ndwi = np.full((32, 32), 0.2, dtype=float)

    result = extract_water_mask(ndwi)

    assert result.used_fallback is True
    assert result.mask.any()


def test_runoff_potential_index_returns_stable_value() -> None:
    dem = np.array(
        [
            [120.0, 110.0, 100.0],
            [130.0, 118.0, 105.0],
            [150.0, 132.0, 111.0],
        ]
    )

    value = compute_runoff_potential_index(dem, resolution_m=30.0)

    assert value > 0.0
    assert np.isfinite(value)


def test_quality_report_marks_low_valid_ratio() -> None:
    ndvi = np.array([[0.2, 0.3], [0.25, 0.4]], dtype=float)
    observation = RasterObservation(
        year=2025,
        bounds=(0.0, 0.0, 60.0, 60.0),
        resolution_m=30.0,
        blue_band=np.full((2, 2), 0.1),
        green_band=np.full((2, 2), 0.2),
        red_band=np.full((2, 2), 0.15),
        nir_band=np.full((2, 2), 0.4),
        dem=np.full((2, 2), 100.0),
        precipitation=np.full((2, 2), 700.0),
        land_use_intensity=np.full((2, 2), 0.3),
        qa_mask=np.array([[True, False], [False, False]]),
    )

    report = build_quality_report({2025: ndvi}, {2025: observation})

    assert report["status"] == "warning"
    assert report["issues"]


def test_response_classification_rules() -> None:
    assert classify_response(0.03, 40.0) == "recovery"
    assert classify_response(-0.05, 60.0) == "degradation"
    assert classify_response(0.0, 90.0) == "stable"


def test_demo_provider_returns_bundle() -> None:
    request = DemoProvider().load_observation_bundle(
        type(
            "Request",
            (),
            {
                "study_area": "songhua",
                "years": [1995, 2005],
                "season_months": (5, 9),
                "composite_strategy": "median",
                "use_cache": True,
            },
        )()
    )

    assert request.provider_name == "demo"
    assert set(request.observations) == {1995, 2005}
    assert not request.boundary_gdf.empty


def test_public_stac_chirps_falls_back_to_v2_before_deadline() -> None:
    provider = PublicStacProvider(
        url_exists=lambda url: "CHIRPS-2.0" in url,
        today_fn=lambda: date(2026, 3, 14),
    )

    source = provider._resolve_chirps_source(2020, 5)

    assert source["version"] == "v2"
    assert source["available"] is True
    assert source["fallbacks"]


def test_public_stac_cache_key_includes_grid_and_season(tmp_path: Path) -> None:
    app_config = config.AppConfig(cache_root=tmp_path, analysis_grid_size=512)
    provider = PublicStacProvider(app_config=app_config)
    request = AnalysisRequest(
        study_area="songhua",
        start_year=1995,
        end_year=1995,
        year_step=10,
        provider="public_stac",
        season_months=(5, 9),
        composite_strategy="median",
    )

    path = provider._cache_path(request, 1995)

    assert "0509" in path.name
    assert "512" in path.name
