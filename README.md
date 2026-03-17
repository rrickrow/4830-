# 松辽流域分析平台

这个仓库已经从原来的原型项目改造成更接近真实工程的单仓应用，保留 `Streamlit` 主入口，同时提供 `CLI`、运行清单、阶段日志、历史运行列表和更完整的分析产物。

## 当前能力

- 保留 `demo` 离线数据源，可在无网络环境下跑完整分析链路。
- 默认真实数据源改为 `public_stac`，无需账号，使用公开 STAC 和公开 CHIRPS 数据。
- 固定分析阶段：
  `provider_check -> data_prepare -> hydro_extract -> vegetation_analysis -> driver_analysis -> model_analysis -> export -> report`
- 每次运行都会写入 `outputs/runs/<run_id>/`，包含：
  `manifest.json`、`request_snapshot.json`、`provider_health.json`、`quality_report.json`、`source_inventory.json`、`run.log`
- 新增真实工程化产物：
  `segment_metrics.csv`、`response_zones.geojson`、`true_color_panel.png`、`source_inventory.json`
- UI 支持运行控制、环境检查、历史运行查看、阶段进度、真实底图、产物下载。

## 真实数据源

`public_stac` 数据链路固定如下：

- 光学影像：
  `landsat-c2-l2` 为全时段主源，`sentinel-2-l2a` 在 `2017+` 参与融合
- DEM：
  `cop-dem-glo-30`
- 土地覆盖：
  `esa-cci-lc` 用于 `1995-2020`，`esa-worldcover` `2021` 回填 `2021-2025`
- 降水：
  优先尝试 `CHIRPS v3`，若资源缺失则在 `2026-12-31` 前回退 `CHIRPS v2`

## 运行环境

- Python 3.11+
- 建议使用虚拟环境

## 安装

```bash
python -m pip install -r requirements.txt
```

## 启动方式

### 1. Web 控制台

```bash
streamlit run streamlit_app.py
```

### 2. CLI

环境检查：

```bash
python -m river_insight.cli doctor --provider public_stac
python -m river_insight.cli doctor --provider demo
```

执行分析：

```bash
python -m river_insight.cli run --provider public_stac --study-area songhua --start-year 1995 --end-year 2025 --year-step 10 --include-report
```

查看历史运行：

```bash
python -m river_insight.cli list-runs --limit 10
```

## 输出目录

每次运行会在 `outputs/runs/<run_id>/` 下生成独立目录，常见产物包括：

- `annual_metrics.csv`
- `fvc_stats.csv`
- `segment_metrics.csv`
- `centerlines.geojson`
- `nodes.geojson`
- `response_zones.geojson`
- `regression_samples.csv`
- `regression_coefficients.csv`
- `correlation_matrix.csv`
- `driver_contributions.csv`
- `quality_report.json`
- `provider_health.json`
- `source_inventory.json`
- `manifest.json`
- `request_snapshot.json`
- `run.log`
- 多个 PNG 图像
- `analysis_report.pdf`

## 配置

系统支持从本地 `river_insight.toml` 和环境变量加载配置。常用环境变量：

- `RIVER_INSIGHT_PROVIDER`
- `RIVER_INSIGHT_OUTPUT_ROOT`
- `RIVER_INSIGHT_CACHE_ROOT`
- `RIVER_INSIGHT_AOI_PATH`
- `RIVER_INSIGHT_STAC_CATALOG_URL`
- `RIVER_INSIGHT_ANALYSIS_GRID_SIZE`
- `RIVER_INSIGHT_LANDSAT_MAX_CLOUD_COVER`
- `RIVER_INSIGHT_SENTINEL_MAX_CLOUD_COVER`
- `RIVER_INSIGHT_BUFFER_DISTANCES`
- `RIVER_INSIGHT_SEASON_MONTHS`
- `RIVER_INSIGHT_COMPOSITE_STRATEGY`
- `RIVER_INSIGHT_USE_CACHE`
- `RIVER_INSIGHT_ALLOW_DEMO_FALLBACK`

研究区定义文件默认为 [data/study_areas.geojson](/f:/bs项目/4820/data/study_areas.geojson)。

## 注意事项

- 真实 `public_stac` 数据源不需要个人账号，但首次运行会下载真实遥感和降水数据，速度取决于网络。
- 真实运行默认启用缓存，缓存目录在 `.cache/river_insight/`。
- 研究区按统一分析网格处理，不追求整流域原生分辨率全量本地处理。
- 历史运行中如果 `provider=gee`，界面只允许查看旧结果，不允许直接重跑。

## 测试

```bash
python -m pytest -p no:cacheprovider
```

当前测试覆盖包含：

- 配置与请求校验
- `demo` / `public_stac` provider 合同与健康检查
- NDVI、质量检查、响应分区与径流潜势指标
- `demo` 端到端分析
- CLI `doctor` / `list-runs`
