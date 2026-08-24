from typing import Any

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from xgboost import XGBRegressor

from app.domain.phase1 import FEATURES
from app.engineering.surrogate.base import SurrogateModel


class EstimatorSurrogate(SurrogateModel):
    def __init__(self, estimator: Any):
        self._estimator = estimator

    @property
    def estimator(self) -> Any:
        return self._estimator


class ResponseSurfaceModel(EstimatorSurrogate):
    name = "RSM"

    def __init__(self, seed: int = 42):
        super().__init__(
            Pipeline(
                [
                    ("scale", StandardScaler()),
                    ("poly", PolynomialFeatures(2, include_bias=False)),
                    ("model", LinearRegression()),
                ]
            )
        )


class RandomForestModel(EstimatorSurrogate):
    name = "RandomForest"

    def __init__(self, seed: int = 42):
        super().__init__(
            RandomForestRegressor(
                n_estimators=160,
                min_samples_leaf=2,
                random_state=seed,
                n_jobs=1,
            )
        )


class XGBoostModel(EstimatorSurrogate):
    name = "XGBoost"

    def __init__(self, seed: int = 42):
        super().__init__(
            XGBRegressor(
                n_estimators=160,
                max_depth=3,
                learning_rate=0.045,
                subsample=0.9,
                colsample_bytree=0.9,
                objective="reg:squarederror",
                random_state=seed,
                n_jobs=1,
            )
        )


class GaussianProcessModel(EstimatorSurrogate):
    name = "GPR"

    def __init__(self, seed: int = 42):
        super().__init__(
            TransformedTargetRegressor(
                regressor=Pipeline(
                    [
                        ("scale", StandardScaler()),
                        (
                            "model",
                            GaussianProcessRegressor(
                                kernel=ConstantKernel(1.0, (1e-2, 1e2))
                                * Matern(length_scale=np.ones(len(FEATURES)), nu=2.5)
                                + WhiteKernel(
                                    noise_level=1e-5,
                                    noise_level_bounds=(1e-8, 1e0),
                                ),
                                normalize_y=False,
                                n_restarts_optimizer=1,
                                random_state=seed,
                            ),
                        ),
                    ]
                ),
                transformer=StandardScaler(),
            )
        )

    def predict_with_uncertainty(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        transformed_x = self.estimator.regressor_.named_steps["scale"].transform(x)
        mean_scaled, std_scaled = self.estimator.regressor_.named_steps["model"].predict(
            transformed_x, return_std=True
        )
        mean = self.estimator.transformer_.inverse_transform(
            np.asarray(mean_scaled).reshape(-1, 1)
        ).ravel()
        scale = float(self.estimator.transformer_.scale_[0])
        return mean, np.asarray(std_scaled, dtype=float) * scale


def build_surrogate_models(seed: int) -> dict[str, SurrogateModel]:
    models = [
        ResponseSurfaceModel(seed),
        RandomForestModel(seed),
        XGBoostModel(seed),
        GaussianProcessModel(seed),
    ]
    return {model.name: model for model in models}
