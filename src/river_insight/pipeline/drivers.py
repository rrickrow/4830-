from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm


def build_regression_frame(
    annual_metrics: pd.DataFrame,
    fvc_stats: pd.DataFrame,
    driver_table: pd.DataFrame,
) -> pd.DataFrame:
    if annual_metrics.empty or fvc_stats.empty:
        return pd.DataFrame()

    annual = annual_metrics.sort_values("year").reset_index(drop=True)
    drivers = driver_table.set_index("year")
    rows: list[dict[str, object]] = []

    for index in range(1, len(annual)):
        previous = annual.iloc[index - 1]
        current = annual.iloc[index]
        prev_year = int(previous["year"])
        cur_year = int(current["year"])

        current_buffers = fvc_stats[fvc_stats["year"] == cur_year]
        previous_buffers = fvc_stats[fvc_stats["year"] == prev_year].set_index("buffer_label")

        for _, buffer_row in current_buffers.iterrows():
            label = buffer_row["buffer_label"]
            if label not in previous_buffers.index:
                continue
            prev_buffer = previous_buffers.loc[label]
            driver_mean = drivers.loc[[prev_year, cur_year]].mean(numeric_only=True)
            rows.append(
                {
                    "period_label": f"{prev_year}-{cur_year}",
                    "year_start": prev_year,
                    "year_end": cur_year,
                    "buffer_label": label,
                    "delta_fvc": float(buffer_row["fvc_mean"] - prev_buffer["fvc_mean"]),
                    "delta_width": float(current["mean_width_m"] - previous["mean_width_m"]),
                    "delta_migration": float(current["delta_migration_m"])
                    if pd.notna(current["delta_migration_m"])
                    else 0.0,
                    "precipitation_mean": float(driver_mean.get("precipitation_mean", np.nan)),
                    "land_use_intensity_mean": float(
                        driver_mean.get("land_use_intensity_mean", np.nan)
                    ),
                    "slope_mean": float((current["slope_mean"] + previous["slope_mean"]) / 2.0),
                    "runoff_potential_index": float(
                        (current["runoff_potential_index"] + previous["runoff_potential_index"]) / 2.0
                    ),
                }
            )

    return pd.DataFrame(rows)


def run_ols(regression_frame: pd.DataFrame) -> dict[str, object]:
    columns = [
        "delta_width",
        "delta_migration",
        "precipitation_mean",
        "land_use_intensity_mean",
        "slope_mean",
        "runoff_potential_index",
    ]
    required_columns = ["delta_fvc", *columns]
    prepared = regression_frame.copy()
    for column in required_columns:
        if column not in prepared.columns:
            prepared[column] = np.nan

    cleaned = prepared.dropna(subset=required_columns)
    min_samples = max(6, len(columns) + 2)

    if cleaned.empty or len(cleaned) < min_samples:
        empty_frame = pd.DataFrame(columns=["term", "coefficient", "p_value", "ci_low", "ci_high"])
        return {
            "status": "skipped",
            "message": "样本不足，已跳过回归分析。",
            "sample_count": int(len(cleaned)),
            "coefficients": empty_frame,
            "correlation_matrix": pd.DataFrame(),
            "driver_contributions": pd.DataFrame(columns=["term", "abs_coefficient"]),
            "r_squared": None,
            "adjusted_r_squared": None,
        }

    matrix = cleaned[columns].astype(float).copy()
    means = matrix.mean()
    stds = matrix.std(ddof=0).replace(0.0, 1.0)
    standardized = (matrix - means) / stds

    y = cleaned["delta_fvc"].astype(float)
    x = sm.add_constant(standardized, has_constant="add")
    model = sm.OLS(y, x, missing="drop").fit()
    correlation_matrix = cleaned[["delta_fvc", *columns]].corr(numeric_only=True)

    intervals = model.conf_int()
    coefficient_rows = []
    for term in columns:
        coefficient_rows.append(
            {
                "term": term,
                "coefficient": float(model.params[term]),
                "p_value": float(model.pvalues[term]),
                "ci_low": float(intervals.loc[term, 0]),
                "ci_high": float(intervals.loc[term, 1]),
            }
        )

    coefficients = pd.DataFrame(coefficient_rows)
    contributions = (
        coefficients.assign(abs_coefficient=lambda frame: frame["coefficient"].abs())
        .sort_values("abs_coefficient", ascending=False)
        .reset_index(drop=True)
    )

    return {
        "status": "ok",
        "message": "回归分析完成。",
        "sample_count": int(model.nobs),
        "coefficients": coefficients,
        "correlation_matrix": correlation_matrix,
        "driver_contributions": contributions[["term", "abs_coefficient"]],
        "r_squared": float(model.rsquared),
        "adjusted_r_squared": float(model.rsquared_adj),
        "intercept": float(model.params["const"]),
        "summary_text": (
            f"n={int(model.nobs)}, r2={float(model.rsquared):.4f}, "
            f"adj_r2={float(model.rsquared_adj):.4f}"
        ),
    }
