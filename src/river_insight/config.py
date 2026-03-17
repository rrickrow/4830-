from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import tomllib


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DEMO_DATA_DIR = DATA_DIR / "demo"
AOI_FILE = DATA_DIR / "study_areas.geojson"
OUTPUT_ROOT = ROOT_DIR / "outputs"
RUNS_ROOT = OUTPUT_ROOT / "runs"
DEFAULT_CONFIG_PATH = ROOT_DIR / "river_insight.toml"

ALLOWED_STUDY_AREAS = ("songhua", "liaohe", "combined")
STUDY_AREA_LABELS = {
    "songhua": "松花江流域",
    "liaohe": "辽河流域",
    "combined": "松辽联合区域",
}

ALLOWED_PROVIDERS = ("demo", "public_stac")
PROVIDER_LABELS = {
    "demo": "离线演示数据",
    "public_stac": "公开 STAC 遥感数据",
}

ALLOWED_COMPOSITE_STRATEGIES = ("median", "mean")

BASE_YEARS = (1995, 2005, 2015, 2025)
DEFAULT_START_YEAR = 1995
DEFAULT_END_YEAR = 2025
DEFAULT_YEAR_STEP = 10
DEFAULT_PROVIDER = "public_stac"
DEFAULT_INCLUDE_REPORT = True
DEFAULT_SEASON_MONTHS = (5, 9)
DEFAULT_COMPOSITE_STRATEGY = "median"
DEFAULT_USE_CACHE = True
DEFAULT_ALLOW_DEMO_FALLBACK = False

DEFAULT_STAC_CATALOG_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
DEFAULT_ANALYSIS_GRID_SIZE = 512
DEFAULT_LANDSAT_MAX_CLOUD_COVER = 80.0
DEFAULT_SENTINEL_MAX_CLOUD_COVER = 65.0
DEFAULT_ENABLE_TRUE_COLOR_PREVIEW = True
DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0

PUBLIC_STAC_COLLECTIONS = {
    "landsat": "landsat-c2-l2",
    "sentinel": "sentinel-2-l2a",
    "dem": "cop-dem-glo-30",
    "landcover_cci": "esa-cci-lc",
    "landcover_worldcover": "esa-worldcover",
}

CHIRPS_V3_BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-3.0/global_monthly/cogs"
CHIRPS_V2_BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/cogs"
CHIRPS_V3_FALLBACK_DEADLINE = date(2026, 12, 31)

RASTER_SIZE = 256
RESOLUTION_M = 30.0
PIXEL_AREA_M2 = RESOLUTION_M * RESOLUTION_M
MIN_CONNECTED_AREA_KM2 = 0.1
MIN_CONNECTED_PIXELS = math.ceil((MIN_CONNECTED_AREA_KM2 * 1_000_000) / PIXEL_AREA_M2)

DEFAULT_BUFFER_DISTANCES_M = (300, 600, 1000)
SEGMENT_LENGTH_M = 1000.0

OTSU_FALLBACK_THRESHOLD = 0.05
FVC_SOIL_DEFAULT = 0.15
FVC_VEG_DEFAULT = 0.86

MAP_CRS = "EPSG:3857"
DISPLAY_CRS = "EPSG:4326"

QUALITY_ZSCORE_THRESHOLD = 1.5
QUALITY_YEARLY_JUMP_THRESHOLD = 0.08
RESPONSE_RECOVERY_DELTA_FVC = 0.02
RESPONSE_DEGRADATION_DELTA_FVC = -0.02
RESPONSE_HIGH_MIGRATION_M = 120.0


@dataclass(slots=True)
class AppConfig:
    default_provider: str = DEFAULT_PROVIDER
    output_root: Path = RUNS_ROOT
    cache_root: Path = ROOT_DIR / ".cache" / "river_insight"
    aoi_path: Path = AOI_FILE
    default_buffer_distances_m: tuple[int, ...] = DEFAULT_BUFFER_DISTANCES_M
    season_months: tuple[int, int] = DEFAULT_SEASON_MONTHS
    composite_strategy: str = DEFAULT_COMPOSITE_STRATEGY
    use_cache: bool = DEFAULT_USE_CACHE
    allow_demo_fallback: bool = DEFAULT_ALLOW_DEMO_FALLBACK
    segment_length_m: float = SEGMENT_LENGTH_M
    stac_catalog_url: str = DEFAULT_STAC_CATALOG_URL
    analysis_grid_size: int = DEFAULT_ANALYSIS_GRID_SIZE
    landsat_max_cloud_cover: float = DEFAULT_LANDSAT_MAX_CLOUD_COVER
    sentinel_max_cloud_cover: float = DEFAULT_SENTINEL_MAX_CLOUD_COVER
    enable_true_color_preview: bool = DEFAULT_ENABLE_TRUE_COLOR_PREVIEW
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS


def load_app_config(
    config_path: Path | None = None,
    environ: dict[str, str] | None = None,
) -> AppConfig:
    env = environ or os.environ
    source = _read_local_config(config_path or DEFAULT_CONFIG_PATH)
    app_section = source.get("app", {})
    paths_section = source.get("paths", {})
    public_stac_section = source.get("public_stac", {})

    default_provider = str(
        env.get("RIVER_INSIGHT_PROVIDER", app_section.get("provider", DEFAULT_PROVIDER))
    )
    output_root = Path(
        env.get("RIVER_INSIGHT_OUTPUT_ROOT", paths_section.get("output_root", str(RUNS_ROOT)))
    )
    cache_root = Path(
        env.get(
            "RIVER_INSIGHT_CACHE_ROOT",
            paths_section.get("cache_root", str(ROOT_DIR / ".cache" / "river_insight")),
        )
    )
    aoi_path = Path(env.get("RIVER_INSIGHT_AOI_PATH", paths_section.get("aoi_path", str(AOI_FILE))))
    buffer_distances = _parse_int_tuple(
        env.get(
            "RIVER_INSIGHT_BUFFER_DISTANCES",
            app_section.get("buffer_distances_m", DEFAULT_BUFFER_DISTANCES_M),
        )
    )
    season_months = _parse_int_tuple(
        env.get("RIVER_INSIGHT_SEASON_MONTHS", app_section.get("season_months", DEFAULT_SEASON_MONTHS))
    )
    composite_strategy = str(
        env.get(
            "RIVER_INSIGHT_COMPOSITE_STRATEGY",
            app_section.get("composite_strategy", DEFAULT_COMPOSITE_STRATEGY),
        )
    )
    use_cache = _parse_bool(
        env.get("RIVER_INSIGHT_USE_CACHE", app_section.get("use_cache", DEFAULT_USE_CACHE))
    )
    allow_demo_fallback = _parse_bool(
        env.get(
            "RIVER_INSIGHT_ALLOW_DEMO_FALLBACK",
            app_section.get("allow_demo_fallback", DEFAULT_ALLOW_DEMO_FALLBACK),
        )
    )
    segment_length_m = float(
        env.get(
            "RIVER_INSIGHT_SEGMENT_LENGTH_M",
            app_section.get("segment_length_m", SEGMENT_LENGTH_M),
        )
    )
    stac_catalog_url = str(
        env.get(
            "RIVER_INSIGHT_STAC_CATALOG_URL",
            public_stac_section.get("catalog_url", DEFAULT_STAC_CATALOG_URL),
        )
    )
    analysis_grid_size = int(
        env.get(
            "RIVER_INSIGHT_ANALYSIS_GRID_SIZE",
            public_stac_section.get("analysis_grid_size", DEFAULT_ANALYSIS_GRID_SIZE),
        )
    )
    landsat_max_cloud_cover = float(
        env.get(
            "RIVER_INSIGHT_LANDSAT_MAX_CLOUD_COVER",
            public_stac_section.get("landsat_max_cloud_cover", DEFAULT_LANDSAT_MAX_CLOUD_COVER),
        )
    )
    sentinel_max_cloud_cover = float(
        env.get(
            "RIVER_INSIGHT_SENTINEL_MAX_CLOUD_COVER",
            public_stac_section.get("sentinel_max_cloud_cover", DEFAULT_SENTINEL_MAX_CLOUD_COVER),
        )
    )
    enable_true_color_preview = _parse_bool(
        env.get(
            "RIVER_INSIGHT_ENABLE_TRUE_COLOR_PREVIEW",
            public_stac_section.get("enable_true_color_preview", DEFAULT_ENABLE_TRUE_COLOR_PREVIEW),
        )
    )
    request_timeout_seconds = float(
        env.get(
            "RIVER_INSIGHT_REQUEST_TIMEOUT_SECONDS",
            public_stac_section.get("request_timeout_seconds", DEFAULT_REQUEST_TIMEOUT_SECONDS),
        )
    )

    app_config = AppConfig(
        default_provider=default_provider,
        output_root=output_root,
        cache_root=cache_root,
        aoi_path=aoi_path,
        default_buffer_distances_m=buffer_distances,
        season_months=_normalize_season_months(season_months),
        composite_strategy=composite_strategy,
        use_cache=use_cache,
        allow_demo_fallback=allow_demo_fallback,
        segment_length_m=segment_length_m,
        stac_catalog_url=stac_catalog_url,
        analysis_grid_size=analysis_grid_size,
        landsat_max_cloud_cover=landsat_max_cloud_cover,
        sentinel_max_cloud_cover=sentinel_max_cloud_cover,
        enable_true_color_preview=enable_true_color_preview,
        request_timeout_seconds=request_timeout_seconds,
    )
    validate_app_config(app_config)
    return app_config


def validate_app_config(app_config: AppConfig) -> None:
    if app_config.default_provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"不支持的默认数据源: {app_config.default_provider}")
    if app_config.composite_strategy not in ALLOWED_COMPOSITE_STRATEGIES:
        raise ValueError(f"不支持的年度合成策略: {app_config.composite_strategy}")
    if not app_config.aoi_path.exists():
        raise ValueError(f"研究区定义文件不存在: {app_config.aoi_path}")
    if not app_config.default_buffer_distances_m:
        raise ValueError("缓冲区距离不能为空")
    if tuple(sorted(app_config.default_buffer_distances_m)) != app_config.default_buffer_distances_m:
        raise ValueError("缓冲区距离必须按升序排列")
    if app_config.segment_length_m <= 0:
        raise ValueError("河道分段长度必须大于 0")
    if app_config.analysis_grid_size < 128:
        raise ValueError("analysis_grid_size 不能小于 128")
    if not app_config.stac_catalog_url.startswith("https://"):
        raise ValueError("STAC catalog URL 必须使用 https")
    if not (0.0 <= app_config.landsat_max_cloud_cover <= 100.0):
        raise ValueError("Landsat 云量阈值必须位于 0-100 之间")
    if not (0.0 <= app_config.sentinel_max_cloud_cover <= 100.0):
        raise ValueError("Sentinel 云量阈值必须位于 0-100 之间")
    if app_config.request_timeout_seconds <= 0:
        raise ValueError("网络请求超时时间必须大于 0")


def _read_local_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _parse_int_tuple(value: Any) -> tuple[int, ...]:
    if isinstance(value, tuple):
        return tuple(int(item) for item in value)
    if isinstance(value, list):
        return tuple(int(item) for item in value)
    if isinstance(value, str):
        if not value.strip():
            return tuple()
        return tuple(int(item.strip()) for item in value.split(","))
    return tuple(int(item) for item in value)


def _normalize_season_months(value: tuple[int, ...]) -> tuple[int, int]:
    if len(value) != 2:
        raise ValueError("生长季月份必须由开始月和结束月组成")
    start_month, end_month = (int(item) for item in value)
    if start_month < 1 or end_month > 12 or start_month > end_month:
        raise ValueError("生长季月份范围无效")
    return (start_month, end_month)
