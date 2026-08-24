from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Self

import joblib
import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


class SurrogateModel(ABC):
    """Uniform lifecycle contract for every engineering surrogate."""

    name: str

    @property
    @abstractmethod
    def estimator(self) -> Any: ...

    def fit(self, x: np.ndarray, y: np.ndarray) -> Self:
        self.estimator.fit(x, y)
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self.estimator.predict(x), dtype=float)

    def evaluate(self, x: np.ndarray, y: np.ndarray) -> dict[str, float]:
        predicted = self.predict(x)
        return {
            "r2": float(r2_score(y, predicted)),
            "rmse": float(mean_squared_error(y, predicted) ** 0.5),
            "mae": float(mean_absolute_error(y, predicted)),
        }

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, destination)

    @classmethod
    def load(cls, path: str | Path) -> Self:
        model = joblib.load(path)
        if not isinstance(model, cls):
            raise TypeError(f"Artifact contains {type(model).__name__}, expected {cls.__name__}")
        return model
