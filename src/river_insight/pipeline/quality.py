from __future__ import annotations

import numpy as np

from river_insight import config
from river_insight.domain.models import QualityIssue, RasterObservation


def build_quality_report(
    ndvi_by_year: dict[int, np.ndarray],
    observations: dict[int, RasterObservation],
) -> dict[str, object]:
    rows: list[dict[str, float | int | bool]] = []
    issues: list[QualityIssue] = []
    years = sorted(ndvi_by_year)
    means = np.array([float(np.nanmean(ndvi_by_year[year])) for year in years], dtype=float)
    zscores = _z_scores(means)

    for index, year in enumerate(years):
        ndvi = ndvi_by_year[year]
        observation = observations[year]
        valid_ratio = float(np.mean(observation.qa_mask.astype(bool)))
        jump = None
        if index > 0:
            jump = float(means[index] - means[index - 1])

        is_anomaly = False
        if valid_ratio < 0.75:
            issues.append(
                QualityIssue(
                    severity="warning",
                    year=year,
                    metric="valid_ratio",
                    message=f"{year} 年有效像元比例偏低（{valid_ratio:.2%}）。",
                )
            )
            is_anomaly = True
        if abs(zscores[index]) >= config.QUALITY_ZSCORE_THRESHOLD:
            issues.append(
                QualityIssue(
                    severity="warning",
                    year=year,
                    metric="ndvi_mean",
                    message=f"{year} 年 NDVI 均值偏离整体分布，z-score={zscores[index]:.2f}。",
                )
            )
            is_anomaly = True
        if jump is not None and abs(jump) >= config.QUALITY_YEARLY_JUMP_THRESHOLD:
            issues.append(
                QualityIssue(
                    severity="warning",
                    year=year,
                    metric="yearly_jump",
                    message=f"{year} 年 NDVI 年际跳变较大（{jump:.3f}）。",
                )
            )
            is_anomaly = True

        rows.append(
            {
                "year": year,
                "ndvi_mean": float(np.nanmean(ndvi)),
                "ndvi_std": float(np.nanstd(ndvi)),
                "valid_ratio": valid_ratio,
                "ndvi_zscore": float(zscores[index]),
                "yearly_jump": jump,
                "is_anomaly": is_anomaly,
            }
        )

    status = "warning" if issues else "ok"
    return {
        "status": status,
        "summary": "发现需要关注的年度质量波动。" if issues else "年度 NDVI 序列质量正常。",
        "issues": [issue.to_dict() for issue in issues],
        "anomaly_years": [row["year"] for row in rows if row["is_anomaly"]],
        "yearly_metrics": rows,
    }


def _z_scores(values: np.ndarray) -> np.ndarray:
    if values.size <= 1:
        return np.zeros_like(values, dtype=float)
    mean = float(np.nanmean(values))
    std = float(np.nanstd(values))
    if std < 1e-9:
        return np.zeros_like(values, dtype=float)
    return (values - mean) / std
