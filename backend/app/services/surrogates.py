import time
import math
from typing import Any

import numpy as np
from sklearn.base import clone
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from scipy import stats

from app.domain.phase1 import FEATURES, RESPONSES
from app.repositories.artifacts import ArtifactRepository
from app.engineering.surrogate.models import build_surrogate_models


def build_models(seed: int) -> dict[str, Any]:
    return {name: model.estimator for name, model in build_surrogate_models(seed).items()}


def records_to_xy(records: list[dict[str, float | int]], response: str) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray([[float(row[name]) for name in FEATURES] for row in records], dtype=float)
    y = np.asarray([float(row[response]) for row in records], dtype=float)
    return x, y


def _serializable_parameters(estimator: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for key, value in estimator.get_params(deep=True).items():
        if isinstance(value, float) and not math.isfinite(value):
            snapshot[key] = None
        elif value is None or isinstance(value, (bool, int, float, str)):
            snapshot[key] = value
        elif isinstance(value, (list, tuple)) and all(
            item is None or isinstance(item, (bool, int, float, str)) for item in value
        ):
            snapshot[key] = list(value)
        else:
            snapshot[key] = str(value)
    return snapshot


def train_surrogates(
    records: list[dict[str, float | int]], seed: int = 42, repository: ArtifactRepository | None = None
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    repository = repository or ArtifactRepository()
    bundle: dict[str, Any] = {"features": FEATURES, "responses": {}}
    metrics_by_response: dict[str, Any] = {}
    selected: dict[str, str] = {}
    hyperparameters: dict[str, dict[str, Any]] = {}

    for response in RESPONSES:
        x, y = records_to_xy(records, response)
        x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.22, random_state=seed)
        folds = min(5, max(3, len(x_train) // 8))
        cv = KFold(n_splits=folds, shuffle=True, random_state=seed)
        response_models: dict[str, Any] = {}
        response_parameters: dict[str, Any] = {}
        response_metrics: list[dict[str, float | str]] = []

        for name, estimator in build_models(seed).items():
            response_parameters[name] = _serializable_parameters(estimator)
            start = time.perf_counter()
            estimator.fit(x_train, y_train)
            training_ms = (time.perf_counter() - start) * 1000
            inference_start = time.perf_counter()
            predicted = estimator.predict(x_test)
            inference_ms = (time.perf_counter() - inference_start) * 1000
            cv_rmse = float(
                -cross_val_score(
                    clone(estimator), x_train, y_train, cv=cv, scoring="neg_root_mean_squared_error", n_jobs=1
                ).mean()
            )
            metrics = {
                "model": name,
                "r2": round(float(r2_score(y_test, predicted)), 6),
                "rmse": round(float(mean_squared_error(y_test, predicted) ** 0.5), 6),
                "mae": round(float(mean_absolute_error(y_test, predicted)), 6),
                "cv_rmse": round(cv_rmse, 6),
                "training_ms": round(training_ms, 3),
                "inference_ms": round(inference_ms, 3),
                "inference_ms_per_sample": round(inference_ms / max(len(y_test), 1), 6),
                "generalization_error": round(float(mean_squared_error(y_test, predicted) ** 0.5), 6),
                "residual_distribution": {
                    "mean": round(float(np.mean(y_test - predicted)), 6),
                    "std": round(float(np.std(y_test - predicted)), 6),
                    "skewness": round(float(stats.skew(y_test - predicted)), 6),
                    "kurtosis": round(float(stats.kurtosis(y_test - predicted)), 6),
                },
            }
            response_metrics.append(metrics)
            estimator.fit(x, y)
            response_models[name] = estimator

        response_metrics.sort(key=lambda row: float(row["cv_rmse"]))
        winner = str(response_metrics[0]["model"])
        selected[response] = winner
        metrics_by_response[response] = response_metrics
        bundle["responses"][response] = {"selected": winner, "models": response_models}
        hyperparameters[response] = response_parameters

    fingerprint = {
        "seed": seed,
        "rows": len(records),
        "selected": selected,
        "metrics": metrics_by_response,
        "hyperparameters": hyperparameters,
        "evaluation": {
            "test_fraction": 0.22,
            "cross_validation": "shuffled KFold",
            "selection_rule": "lowest cross-validated RMSE",
            "training_r2_used_for_selection": False,
        },
    }
    model_id = repository.version(fingerprint, "model")
    repository.save_model(model_id, bundle, {**fingerprint, "model_id": model_id})
    return model_id, metrics_by_response, selected


def predict_bundle(bundle: dict[str, Any], rows: np.ndarray) -> dict[str, np.ndarray]:
    predictions: dict[str, np.ndarray] = {}
    for response, configured in bundle["responses"].items():
        model = configured["models"][configured["selected"]]
        predictions[response] = np.asarray(model.predict(rows), dtype=float)
    return predictions


def predict_gpr(bundle: dict[str, Any], response: str, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return GPR mean and one-standard-deviation uncertainty in physical response units."""
    estimator = bundle["responses"][response]["models"]["GPR"]
    regressor = estimator.regressor_
    transformed_x = regressor.named_steps["scale"].transform(rows)
    mean_scaled, std_scaled = regressor.named_steps["model"].predict(transformed_x, return_std=True)
    mean = estimator.transformer_.inverse_transform(np.asarray(mean_scaled).reshape(-1, 1)).ravel()
    scale = float(estimator.transformer_.scale_[0])
    return mean, np.asarray(std_scaled, dtype=float) * scale


def predict_design(bundle: dict[str, Any], design: dict[str, float | int]) -> dict[str, Any]:
    row = np.asarray([[float(design[name]) for name in FEATURES]], dtype=float)
    result = {name: round(float(values[0]), 6) for name, values in predict_bundle(bundle, row).items()}
    gpr_entry = bundle["responses"]["t_max"]["models"].get("GPR")
    if gpr_entry is not None:
        _, uncertainty = predict_gpr(bundle, "t_max", row)
        result["t_max_uncertainty"] = round(float(uncertainty[0]), 6)
    return result
