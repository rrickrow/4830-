from __future__ import annotations

import json
from pathlib import Path

try:
    import folium
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    folium = None

import geopandas as gpd
import matplotlib.image as mpimg
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from river_insight import config
from river_insight.domain.models import AnalysisRequest, AnalysisResult
from river_insight.labels import APP_CAPTION, APP_TITLE, PROVIDER_DESCRIPTIONS, STAGE_LABELS
from river_insight.providers.aoi import get_study_area_boundary
from river_insight.services.analysis_service import AnalysisService


def render_app() -> None:
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption(APP_CAPTION)

    service = AnalysisService()
    history = service.list_runs(limit=30)
    history_map = {item["run_id"]: item for item in history}

    request = _render_controls(service, history_map)
    _render_doctor_panel(service)

    if request is not None and st.button("开始分析", type="primary", use_container_width=True):
        _execute_request(service, request)

    current_result: AnalysisResult | None = st.session_state.get("analysis_result")
    selected_run_id = st.session_state.get("selected_run_id")
    if current_result is not None and (selected_run_id is None or selected_run_id == current_result.run_id):
        _render_result_view(current_result)
    elif selected_run_id and selected_run_id in history_map:
        _render_history_view(history_map[selected_run_id])

    if st.session_state.get("analysis_error"):
        st.error(st.session_state["analysis_error"])


def _render_controls(service: AnalysisService, history_map: dict[str, dict[str, object]]) -> AnalysisRequest | None:
    default_request = service.build_default_request()

    with st.sidebar:
        st.subheader("运行控制")
        selected_run = st.selectbox(
            "历史运行",
            options=["(当前参数)"] + list(history_map),
            format_func=lambda value: value
            if value == "(当前参数)"
            else f"{value} · {history_map[value].get('status', 'unknown')}",
        )
        if selected_run != "(当前参数)":
            st.session_state["selected_run_id"] = selected_run
            payload = history_map[selected_run].get("request_snapshot", {})
            provider_name = str(payload.get("provider", "demo")) if isinstance(payload, dict) else "demo"
            rerun_disabled = provider_name not in config.ALLOWED_PROVIDERS
            if rerun_disabled:
                st.info(f"`{provider_name}` 已退役，只能查看历史结果，不能直接重跑。")
            if st.button("按历史参数重跑", use_container_width=True, disabled=rerun_disabled):
                request = _request_from_payload(payload)
                _execute_request(service, request)
        elif "selected_run_id" in st.session_state:
            st.session_state.pop("selected_run_id")

        st.markdown("---")
        st.caption("数据源说明")
        for key, description in PROVIDER_DESCRIPTIONS.items():
            st.write(f"`{key}`: {description}")

    with st.container(border=True):
        cols = st.columns(7)
        study_area = cols[0].selectbox("研究区", options=config.ALLOWED_STUDY_AREAS, index=0)
        start_year = int(
            cols[1].number_input(
                "开始年份",
                min_value=config.BASE_YEARS[0],
                max_value=config.BASE_YEARS[-1],
                value=default_request.start_year,
                step=5,
            )
        )
        end_year = int(
            cols[2].number_input(
                "结束年份",
                min_value=config.BASE_YEARS[0],
                max_value=config.BASE_YEARS[-1],
                value=default_request.end_year,
                step=5,
            )
        )
        year_step = int(cols[3].selectbox("年份步长", options=[5, 10, 15], index=1))
        provider = cols[4].selectbox(
            "数据源",
            options=config.ALLOWED_PROVIDERS,
            index=config.ALLOWED_PROVIDERS.index(default_request.provider),
        )
        include_report = cols[5].checkbox("生成报告", value=default_request.include_report)
        use_cache = cols[6].checkbox("启用缓存", value=default_request.use_cache)

        cols2 = st.columns(5)
        season_months = cols2[0].select_slider(
            "生长季月份",
            options=list(range(1, 13)),
            value=default_request.season_months,
        )
        composite_strategy = cols2[1].selectbox(
            "年度合成策略",
            options=config.ALLOWED_COMPOSITE_STRATEGIES,
            index=config.ALLOWED_COMPOSITE_STRATEGIES.index(default_request.composite_strategy),
        )
        allow_demo_fallback = cols2[2].checkbox("允许回退 demo", value=default_request.allow_demo_fallback)
        buffer_text = cols2[3].text_input(
            "缓冲区(m)",
            value=",".join(str(item) for item in default_request.buffer_distances_m),
        )
        cols2[4].metric("历史运行数", len(history_map))

    try:
        request = AnalysisRequest(
            study_area=study_area,
            start_year=start_year,
            end_year=end_year,
            year_step=year_step,
            provider=provider,
            include_report=include_report,
            buffer_distances_m=tuple(int(item.strip()) for item in buffer_text.split(",") if item.strip()),
            season_months=tuple(int(item) for item in season_months),
            composite_strategy=composite_strategy,
            use_cache=use_cache,
            allow_demo_fallback=allow_demo_fallback,
        )
        request.validate()
        return request
    except ValueError as exc:
        st.warning(str(exc))
        return None


def _render_doctor_panel(service: AnalysisService) -> None:
    with st.expander("环境检查", expanded=False):
        col_left, col_right = st.columns([0.25, 0.75])
        with col_left:
            provider = st.selectbox("检查数据源", options=config.ALLOWED_PROVIDERS, key="doctor_provider")
            study_area = st.selectbox("检查区域", options=config.ALLOWED_STUDY_AREAS, key="doctor_study_area")
            if st.button("执行 doctor", use_container_width=True):
                st.session_state["doctor_result"] = service.doctor(provider_name=provider, study_area=study_area)
        with col_right:
            doctor_result = st.session_state.get("doctor_result")
            if doctor_result:
                st.json(doctor_result, expanded=False)


def _execute_request(service: AnalysisService, request: AnalysisRequest) -> None:
    try:
        with st.spinner("正在执行分析，请稍候..."):
            result = service.run(request)
        st.session_state["analysis_result"] = result
        st.session_state["analysis_error"] = None
        st.session_state["selected_run_id"] = result.run_id
    except Exception as exc:  # pragma: no cover - streamlit runtime path
        st.session_state["analysis_error"] = str(exc)


def _render_result_view(result: AnalysisResult) -> None:
    _render_common_view(
        request_payload=result.manifest.request_snapshot,
        provider_health=result.provider_health.to_dict(),
        stage_records=[record.to_dict() for record in result.manifest.stage_records],
        warnings=result.warnings,
        boundary=result.boundary_gdf,
        centerlines=result.centerlines_gdf,
        nodes=result.nodes_gdf,
        response_zones=result.response_zones_gdf,
        annual_metrics=result.annual_metrics,
        fvc_stats=result.fvc_stats,
        segment_metrics=result.segment_metrics,
        quality_report=result.quality_report,
        regression_summary=result.regression_summary,
        output_dir=result.output_dir,
        artifact_map={key: value for key, value in result.artifacts.items() if isinstance(value, Path)},
        source_inventory=result.source_inventory,
    )


def _render_history_view(history_record: dict[str, object]) -> None:
    artifact_map = {
        item["key"]: Path(item["path"])
        for item in history_record.get("artifacts", [])
        if isinstance(item, dict) and "key" in item and "path" in item
    }
    request_payload = history_record.get("request_snapshot", {})
    study_area = str(history_record.get("study_area", "songhua"))
    boundary = get_study_area_boundary(study_area)
    centerlines = _read_geojson(artifact_map.get("centerlines_geojson"))
    nodes = _read_geojson(artifact_map.get("nodes_geojson"))
    response_zones = _read_geojson(artifact_map.get("response_zones_geojson"))
    annual_metrics = _read_csv(artifact_map.get("annual_metrics_csv"))
    fvc_stats = _read_csv(artifact_map.get("fvc_stats_csv"))
    segment_metrics = _read_csv(artifact_map.get("segment_metrics_csv"))
    quality_report = _read_json(artifact_map.get("quality_report_json")) or {}
    provider_health = _read_json(artifact_map.get("provider_health_json")) or {}
    regression_summary = _read_json(artifact_map.get("regression_summary_json")) or {}
    source_inventory = _read_json(artifact_map.get("source_inventory_json")) or {}

    _render_common_view(
        request_payload=request_payload if isinstance(request_payload, dict) else {},
        provider_health=provider_health,
        stage_records=history_record.get("stage_records", []),
        warnings=list(history_record.get("warnings", [])),
        boundary=boundary,
        centerlines=centerlines,
        nodes=nodes,
        response_zones=response_zones,
        annual_metrics=annual_metrics,
        fvc_stats=fvc_stats,
        segment_metrics=segment_metrics,
        quality_report=quality_report,
        regression_summary=regression_summary,
        output_dir=Path(str(history_record["output_dir"])) if "output_dir" in history_record else None,
        artifact_map=artifact_map,
        source_inventory=source_inventory,
    )


def _render_common_view(
    request_payload: dict[str, object],
    provider_health: dict[str, object],
    stage_records: list[dict[str, object]],
    warnings: list[str],
    boundary: gpd.GeoDataFrame | None,
    centerlines: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    response_zones: gpd.GeoDataFrame,
    annual_metrics: pd.DataFrame,
    fvc_stats: pd.DataFrame,
    segment_metrics: pd.DataFrame,
    quality_report: dict[str, object],
    regression_summary: dict[str, object],
    output_dir: Path | None,
    artifact_map: dict[str, Path],
    source_inventory: dict[str, object],
) -> None:
    tabs = st.tabs(["运行总览", "地图", "植被响应", "驱动评估", "质量检查", "数据来源", "导出产物"])

    with tabs[0]:
        _render_overview(request_payload, provider_health, stage_records, warnings)

    with tabs[1]:
        _render_map_tab(
            boundary=boundary,
            centerlines=centerlines,
            nodes=nodes,
            response_zones=response_zones,
            artifact_map=artifact_map,
            source_inventory=source_inventory,
        )

    with tabs[2]:
        _render_vegetation_tab(fvc_stats, artifact_map)

    with tabs[3]:
        _render_driver_tab(regression_summary, segment_metrics, artifact_map)

    with tabs[4]:
        _render_quality_tab(quality_report, artifact_map)

    with tabs[5]:
        _render_source_inventory(source_inventory)

    with tabs[6]:
        _render_export_tab(output_dir, artifact_map)


def _render_overview(
    request_payload: dict[str, object],
    provider_health: dict[str, object],
    stage_records: list[dict[str, object]],
    warnings: list[str],
) -> None:
    col_left, col_right = st.columns([0.5, 0.5])
    with col_left:
        st.subheader("请求快照")
        st.json(request_payload, expanded=False)
        for item in warnings:
            st.warning(item)
    with col_right:
        st.subheader("数据源健康状态")
        st.json(provider_health, expanded=False)

    if stage_records:
        stage_frame = pd.DataFrame(stage_records)
        if "stage" in stage_frame.columns:
            stage_frame["stage"] = stage_frame["stage"].map(lambda value: STAGE_LABELS.get(value, value))
        st.subheader("阶段进度")
        st.dataframe(stage_frame, use_container_width=True, hide_index=True)


def _render_map_tab(
    boundary: gpd.GeoDataFrame | None,
    centerlines: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    response_zones: gpd.GeoDataFrame,
    artifact_map: dict[str, Path],
    source_inventory: dict[str, object],
) -> None:
    col_left, col_right = st.columns([1.1, 0.9])
    with col_left:
        if boundary is not None:
            _show_map(boundary, centerlines, nodes, response_zones, artifact_map, source_inventory)
    with col_right:
        _show_image(artifact_map.get("true_color_panel_png"), "真彩色合成预览")
        _show_image(artifact_map.get("water_masks_panel_png"), "年度水体掩膜")


def _render_vegetation_tab(fvc_stats: pd.DataFrame, artifact_map: dict[str, Path]) -> None:
    col_left, col_right = st.columns(2)
    with col_left:
        _show_image(artifact_map.get("fvc_heatmap_png"), "FVC 热力图")
    with col_right:
        _show_image(artifact_map.get("coupling_png"), "河道-植被耦合散点图")
    st.subheader("缓冲带统计")
    st.dataframe(fvc_stats, use_container_width=True, hide_index=True)


def _render_driver_tab(
    regression_summary: dict[str, object],
    segment_metrics: pd.DataFrame,
    artifact_map: dict[str, Path],
) -> None:
    col_left, col_right = st.columns([0.55, 0.45])
    with col_left:
        _show_image(artifact_map.get("regression_png"), "回归系数图")
    with col_right:
        st.metric("回归样本数", regression_summary.get("sample_count"))
        st.write(f"R²: {regression_summary.get('r_squared')}")
        st.write(f"调整后 R²: {regression_summary.get('adjusted_r_squared')}")
    for key in ("regression_coefficients_csv", "driver_contributions_csv", "correlation_matrix_csv"):
        table = _read_csv(artifact_map.get(key))
        if not table.empty:
            st.subheader(key)
            st.dataframe(table, use_container_width=True, hide_index=True)
    if not segment_metrics.empty:
        st.subheader("河道分段指标")
        st.dataframe(segment_metrics.head(200), use_container_width=True, hide_index=True)


def _render_quality_tab(quality_report: dict[str, object], artifact_map: dict[str, Path]) -> None:
    _show_image(artifact_map.get("ndvi_quality_png"), "NDVI 质量曲线")
    st.subheader("质量报告")
    st.write(quality_report.get("summary", "无"))
    issues = quality_report.get("issues", [])
    if issues:
        st.dataframe(pd.DataFrame(issues), use_container_width=True, hide_index=True)
    yearly_metrics = quality_report.get("yearly_metrics", [])
    if yearly_metrics:
        st.subheader("年度质量指标")
        st.dataframe(pd.DataFrame(yearly_metrics), use_container_width=True, hide_index=True)


def _render_source_inventory(source_inventory: dict[str, object]) -> None:
    if not source_inventory:
        st.info("当前运行没有 source inventory。")
        return
    st.json(source_inventory, expanded=False)


def _render_export_tab(output_dir: Path | None, artifact_map: dict[str, Path]) -> None:
    if output_dir is not None:
        st.write(f"输出目录：`{output_dir}`")
    for key, path in artifact_map.items():
        if not path.exists():
            continue
        st.write(f"{key}: `{path.name}`")
        with path.open("rb") as handle:
            st.download_button(
                label=f"下载 {path.name}",
                data=handle.read(),
                file_name=path.name,
                key=f"download_{key}",
            )


def _show_image(path: Path | None, caption: str) -> None:
    if path is None or not path.exists():
        st.info(f"{caption} 暂不可用")
        return
    st.image(str(path), caption=caption, use_container_width=True)


def _show_map(
    boundary: gpd.GeoDataFrame,
    centerlines_gdf: gpd.GeoDataFrame,
    nodes_gdf: gpd.GeoDataFrame,
    response_zones_gdf: gpd.GeoDataFrame,
    artifact_map: dict[str, Path],
    source_inventory: dict[str, object],
) -> None:
    if folium is None:
        st.info("地图组件依赖 `folium`，当前仅显示静态分析结果。")
        return

    display_boundary = boundary.to_crs(config.DISPLAY_CRS)
    center = display_boundary.geometry.union_all().centroid if hasattr(display_boundary.geometry, "union_all") else display_boundary.geometry.unary_union.centroid
    fmap = folium.Map(location=[center.y, center.x], zoom_start=8, tiles=None)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(fmap)
    folium.TileLayer("CartoDB positron", name="CartoDB Positron").add_to(fmap)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri World Imagery",
    ).add_to(fmap)

    folium.GeoJson(
        data=display_boundary.to_json(drop_id=True),
        name="AOI",
        style_function=lambda _: {
            "color": "#1f2937",
            "weight": 2,
            "fillOpacity": 0.05,
            "fillColor": "#f3f4f6",
        },
    ).add_to(fmap)

    if centerlines_gdf is not None and not centerlines_gdf.empty:
        centerlines = centerlines_gdf.to_crs(config.DISPLAY_CRS)
        folium.GeoJson(
            data=centerlines.to_json(drop_id=True),
            name="Centerlines",
            style_function=lambda _: {"color": "#0f766e", "weight": 2},
        ).add_to(fmap)

    if response_zones_gdf is not None and not response_zones_gdf.empty:
        response_display = response_zones_gdf.to_crs(config.DISPLAY_CRS)
        folium.GeoJson(
            data=response_display.to_json(drop_id=True),
            name="Response Zones",
            style_function=lambda feature: {
                "color": {
                    "recovery": "#16a34a",
                    "stable": "#2563eb",
                    "degradation": "#dc2626",
                }.get(feature["properties"].get("response_class"), "#6b7280"),
                "weight": 3,
            },
        ).add_to(fmap)

    if nodes_gdf is not None and not nodes_gdf.empty:
        points = nodes_gdf.to_crs(config.DISPLAY_CRS)
        for _, row in points.iterrows():
            geom = row.geometry
            folium.CircleMarker(
                location=[geom.y, geom.x],
                radius=4,
                color="#b91c1c",
                fill=True,
                fill_opacity=0.8,
                popup=f"{row['node_type']} (degree={row['degree']})",
            ).add_to(fmap)

    bounds = source_inventory.get("preview_bounds_wgs84")
    if isinstance(bounds, list) and len(bounds) == 4:
        overlay_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
        true_color_path = artifact_map.get("true_color_latest_png")
        if true_color_path and true_color_path.exists():
            true_color = mpimg.imread(true_color_path)
            folium.raster_layers.ImageOverlay(
                image=true_color,
                bounds=overlay_bounds,
                name="True Color",
                opacity=0.75,
                interactive=False,
            ).add_to(fmap)
        water_mask_path = artifact_map.get("water_mask_latest_png")
        if water_mask_path and water_mask_path.exists():
            water_mask = mpimg.imread(water_mask_path)
            folium.raster_layers.ImageOverlay(
                image=water_mask,
                bounds=overlay_bounds,
                name="Water Mask",
                opacity=0.45,
                interactive=False,
            ).add_to(fmap)

    folium.LayerControl().add_to(fmap)
    components.html(fmap._repr_html_(), height=520)


def _request_from_payload(payload: object) -> AnalysisRequest:
    data = payload if isinstance(payload, dict) else {}
    provider_name = str(data.get("provider", config.DEFAULT_PROVIDER))
    if provider_name not in config.ALLOWED_PROVIDERS:
        provider_name = config.DEFAULT_PROVIDER
    request = AnalysisRequest(
        study_area=str(data.get("study_area", "songhua")),
        start_year=int(data.get("start_year", 1995)),
        end_year=int(data.get("end_year", 2025)),
        year_step=int(data.get("year_step", 10)),
        provider=provider_name,
        include_report=bool(data.get("include_report", True)),
        buffer_distances_m=tuple(int(item) for item in data.get("buffer_distances_m", [300, 600, 1000])),
        season_months=tuple(int(item) for item in data.get("season_months", [5, 9])),
        composite_strategy=str(data.get("composite_strategy", "median")),
        use_cache=bool(data.get("use_cache", True)),
        allow_demo_fallback=bool(data.get("allow_demo_fallback", False)),
    )
    request.validate()
    return request


def _read_csv(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_geojson(path: Path | None) -> gpd.GeoDataFrame:
    if path is None or not path.exists():
        return gpd.GeoDataFrame(geometry=[], crs=config.MAP_CRS)
    return gpd.read_file(path)
