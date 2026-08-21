import time
from typing import Any

import numpy as np
from sklearn.base import clone
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from xgboost import XGBRegressor

from app.domain.phase1 import FEATURES, RESPONSES
from app.repositories.artifacts import ArtifactRepository


def build_models(seed: int) -> dict[str, Any]:
    return {
        "RSM": Pipeline(
            [("scale", StandardScaler()), ("poly", PolynomialFeatures(2, include_bias=False)), ("model", LinearRegression())]
        ),
        "RandomForest": RandomForestRegressor(
            n_estimators=160, min_samples_leaf=2, random_state=seed, n_jobs=1
        ),
        "XGBoost": XGBRegressor(
            n_estimators=160,
            max_depth=3,
            learning_rate=0.045,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            random_state=seed,
            n_jobs=1,
        ),
        "GPR": TransformedTargetRegressor(
            regressor=Pipeline(
                [
                    ("scale", StandardScaler()),
                    (
                        "model",
                        GaussianProcessRegressor(
                            kernel=ConstantKernel(1.0, (1e-2, 1e2))
                            * Matern(length_scale=np.ones(len(FEATURES)), nu=2.5)
                            + WhiteKernel(noise_level=1e-5, noise_level_bounds=(1e-8, 1e0)),
                            normalize_y=False,
                            n_restarts_optimizer=1,
                            random_state=seed,
                        ),
                    ),
                ]
            ),
            transformer=StandardScaler(),
        ),
    }


def records_to_xy(records: list[dict[str, float | int]], response: str) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray([[float(row[name]) for name in FEATURES] for row in records], dtype=float)
    y = np.asarray([float(row[response]) for row in records], dtype=float)
    return x, y


def train_surrogates(
    records: list[dict[str, float | int]], seed: int = 42, repository: ArtifactRepository | None = None
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    repository = repository or ArtifactRepository()
    bundle: dict[str, Any] = {"features": FEATURES, "responses": {}}
    metrics_by_response: dict[str, Any] = {}
    selected: dict[str, str] = {}

    for response in RESPONSES:
        x, y = records_to_xy(records, response)
        x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.22, random_state=seed)
        folds = min(5, max(3, len(x_train) // 8))
        cv = KFold(n_splits=folds, shuffle=True, random_state=seed)
        response_models: dict[str, Any] = {}
        response_metrics: list[dict[str, float | str]] = []

        for name, estimator in build_models(seed).items():
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
            }
            response_metrics.append(metrics)
            estimator.fit(x, y)
            response_models[name] = estimator

        response_metrics.sort(key=lambda row: float(row["cv_rmse"]))
        winner = str(response_metrics[0]["model"])
        selected[response] = winner
        metrics_by_response[response] = response_metrics
        bundle["responses"][response] = {"selected": winner, "models": response_models}

    fingerprint = {
        "seed": seed,
        "rows": len(records),
        "selected": selected,
        "metrics": metrics_by_response,
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


def predict_design(bundle: dict[str, Any], design: dict[str, float | int]) -> dict[str, Any]:
    row = np.asarray([[float(design[name]) for name in FEATURES]], dtype=float)
    result = {name: round(float(values[0]), 6) for name, values in predict_bundle(bundle, row).items()}
    gpr_entry = bundle["responses"]["t_max"]["models"].get("GPR")
    if gpr_entry is not None:
        regressor = gpr_entry.regressor_
        transformed_x = regressor.named_steps["scale"].transform(row)
        _, std_scaled = regressor.named_steps["model"].predict(transformed_x, return_std=True)
        target_scale = float(gpr_entry.transformer_.scale_[0])
        result["t_max_uncertainty"] = round(float(std_scaled[0] * target_scale), 6)
    return result
