import math
from typing import Any

import numpy as np
from scipy import stats
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures

from app.domain.phase1 import FEATURES


def _arrays(records: list[dict[str, float | int]], response: str) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray([[float(row[name]) for name in FEATURES] for row in records], dtype=float)
    y = np.asarray([float(row[response]) for row in records], dtype=float)
    return x, y


def analyze(records: list[dict[str, float | int]], response: str = "t_max") -> dict[str, Any]:
    """Fit a quadratic RSM and return partial-term ANOVA plus residual diagnostics."""
    x, y = _arrays(records, response)
    transformer = PolynomialFeatures(degree=2, include_bias=False)
    design = transformer.fit_transform(x)
    names = transformer.get_feature_names_out(FEATURES).tolist()
    model = LinearRegression().fit(design, y)
    fitted = model.predict(design)
    residuals = y - fitted
    sse = float(np.sum(residuals**2))
    sst = float(np.sum((y - y.mean()) ** 2))
    ssr = max(sst - sse, 0.0)
    df_model = design.shape[1]
    df_residual = max(len(y) - df_model - 1, 1)
    mse = sse / df_residual
    model_f = (ssr / max(df_model, 1)) / max(mse, 1e-12)

    terms: list[dict[str, float | int | str]] = []
    for column, name in enumerate(names):
        reduced = np.delete(design, column, axis=1)
        reduced_fit = LinearRegression().fit(reduced, y).predict(reduced)
        partial_ss = max(float(np.sum((y - reduced_fit) ** 2)) - sse, 0.0)
        f_value = partial_ss / max(mse, 1e-12)
        terms.append(
            {
                "source": name.replace(" ", " × ").replace("^2", "²"),
                "sum_sq": round(partial_ss, 6),
                "df": 1,
                "mean_sq": round(partial_ss, 6),
                "f_value": round(f_value, 5),
                "p_value": round(float(stats.f.sf(f_value, 1, df_residual)), 7),
            }
        )
    terms.sort(key=lambda row: float(row["sum_sq"]), reverse=True)

    residual_std = math.sqrt(max(mse, 1e-12))
    standardized = residuals / residual_std
    qq = stats.probplot(residuals, dist="norm", fit=False)
    hist_count, hist_edges = np.histogram(residuals, bins=min(10, max(5, len(y) // 6)))
    coefficient_rows = [
        {"term": "intercept", "coefficient": round(float(model.intercept_), 8)}
    ] + [
        {"term": name.replace(" ", " × ").replace("^2", "²"), "coefficient": round(float(value), 8)}
        for name, value in zip(names, model.coef_, strict=True)
    ]

    return {
        "response": response,
        "r_squared": round(1.0 - sse / max(sst, 1e-12), 6),
        "rmse": round(float(np.sqrt(np.mean(residuals**2))), 6),
        "anova": [
            {
                "source": "Model",
                "sum_sq": round(ssr, 6),
                "df": df_model,
                "mean_sq": round(ssr / max(df_model, 1), 6),
                "f_value": round(model_f, 5),
                "p_value": round(float(stats.f.sf(model_f, df_model, df_residual)), 7),
            },
            *terms,
            {
                "source": "Residual",
                "sum_sq": round(sse, 6),
                "df": df_residual,
                "mean_sq": round(mse, 6),
                "f_value": 0.0,
                "p_value": 1.0,
            },
        ],
        "coefficients": coefficient_rows,
        "main_effects": [row for row in terms if "×" not in str(row["source"]) and "²" not in str(row["source"])],
        "interactions": [row for row in terms if "×" in str(row["source"])],
        "diagnostics": {
            "residual_vs_fitted": [
                {"fitted": round(float(fit), 6), "residual": round(float(residual), 6)}
                for fit, residual in zip(fitted, residuals, strict=True)
            ],
            "qq_plot": [
                {"theoretical": round(float(theory), 6), "sample": round(float(sample), 6)}
                for theory, sample in zip(qq[0], qq[1], strict=True)
            ],
            "histogram": {
                "counts": hist_count.tolist(),
                "edges": [round(float(value), 6) for value in hist_edges],
            },
            "prediction_error": [round(float(value), 6) for value in residuals],
            "outlier_indices": np.flatnonzero(np.abs(standardized) > 3.0).astype(int).tolist(),
            "shapiro_p_value": round(float(stats.shapiro(residuals).pvalue), 7) if len(y) >= 3 else None,
        },
    }
