from __future__ import annotations

from river_insight import config


APP_TITLE = "松辽流域河道变化与植被响应分析平台"
APP_CAPTION = "基于公开 STAC 遥感数据与离线演示数据的工程化流域分析应用"

STAGE_LABELS = {
    "provider_check": "数据源检查",
    "data_prepare": "数据准备",
    "hydro_extract": "河道提取",
    "vegetation_analysis": "植被分析",
    "driver_analysis": "驱动因子分析",
    "model_analysis": "模型分析",
    "export": "结果导出",
    "report": "报告生成",
}

STATUS_LABELS = {
    "pending": "待执行",
    "running": "执行中",
    "ok": "成功",
    "failed": "失败",
    "warning": "警告",
}

PROVIDER_DESCRIPTIONS = {
    "demo": "使用本地生成的确定性样例数据，适合离线演示与测试。",
    "public_stac": "使用 Microsoft Planetary Computer 公开 STAC 目录和公开 CHIRPS 降水数据，无需账号。",
}


def provider_label(provider_name: str) -> str:
    return config.PROVIDER_LABELS.get(provider_name, provider_name)


def study_area_label(study_area: str) -> str:
    return config.STUDY_AREA_LABELS.get(study_area, study_area)
