from typing import Any

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import ElementwiseProblem
from pymoo.optimize import minimize
from scipy.optimize import differential_evolution

from app.domain.phase1 import FEATURES, OptimizationRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.surrogates import predict_bundle


LOWER = np.asarray([20.0, 0.3, 20.0, 1.0, 0.5])
UPPER = np.asarray([60.0, 1.0, 60.0, 4.0, 5.0])


def _physical_row(vector: np.ndarray) -> np.ndarray:
    row = np.clip(np.asarray(vector, dtype=float), LOWER, UPPER)
    row[0] = round(row[0])
    return row


def _design(row: np.ndarray) -> dict[str, float | int]:
    return {
        name: int(row[index]) if name == "fin_count" else round(float(row[index]), 6)
        for index, name in enumerate(FEATURES)
    }


def _predict(bundle: dict[str, Any], row: np.ndarray) -> dict[str, float]:
    return {key: float(value[0]) for key, value in predict_bundle(bundle, row.reshape(1, -1)).items()}


class SurrogateOptimizationProblem(ElementwiseProblem):
    def __init__(self, bundle: dict[str, Any], request: OptimizationRequest):
        super().__init__(n_var=len(FEATURES), n_obj=len(request.objectives), n_ieq_constr=2, xl=LOWER, xu=UPPER)
        self.bundle = bundle
        self.request = request

    def _evaluate(self, x, out, *args, **kwargs):
        row = _physical_row(x)
        predicted = _predict(self.bundle, row)
        out["F"] = [predicted[name] for name in self.request.objectives]
        out["G"] = [
            predicted["t_max"] - self.request.t_max_limit,
            predicted["pressure_drop"] - self.request.pressure_drop_limit,
        ]


def optimize(request: OptimizationRequest, repository: ArtifactRepository | None = None) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    bundle = repository.load_model(request.model_id)

    if request.mode == "single":
        objective = request.objectives[0]

        def score(vector: np.ndarray) -> float:
            row = _physical_row(vector)
            predicted = _predict(bundle, row)
            penalty = max(predicted["t_max"] - request.t_max_limit, 0.0) * 1e3
            penalty += max(predicted["pressure_drop"] - request.pressure_drop_limit, 0.0) * 1e3
            return predicted[objective] + penalty

        result = differential_evolution(
            score,
            bounds=list(zip(LOWER, UPPER, strict=True)),
            seed=request.seed,
            maxiter=request.generations,
            popsize=max(5, request.population_size // len(FEATURES)),
            polish=True,
            workers=1,
        )
        row = _physical_row(result.x)
        predicted = _predict(bundle, row)
        return {
            "mode": "single",
            "objectives": request.objectives,
            "recommended": {"design": _design(row), "responses": predicted},
            "pareto": [],
            "evaluations": int(result.nfev),
            "success": bool(result.success),
        }

    problem = SurrogateOptimizationProblem(bundle, request)
    algorithm = NSGA2(pop_size=request.population_size, eliminate_duplicates=True)
    result = minimize(
        problem,
        algorithm,
        ("n_gen", request.generations),
        seed=request.seed,
        verbose=False,
        save_history=False,
    )
    if result.X is None:
        return {"mode": "multi", "objectives": request.objectives, "recommended": None, "pareto": []}

    vectors = np.atleast_2d(result.X)
    pareto: list[dict[str, Any]] = []
    for vector in vectors:
        row = _physical_row(vector)
        predicted = _predict(bundle, row)
        pareto.append({"design": _design(row), "responses": predicted})
    pareto.sort(key=lambda item: tuple(item["responses"][name] for name in request.objectives))
    pareto = pareto[:30]
    objective_matrix = np.asarray(
        [[item["responses"][name] for name in request.objectives] for item in pareto], dtype=float
    )
    span = np.maximum(objective_matrix.max(axis=0) - objective_matrix.min(axis=0), 1e-9)
    normalized = (objective_matrix - objective_matrix.min(axis=0)) / span
    recommended_index = int(np.argmin(np.linalg.norm(normalized, axis=1)))
    return {
        "mode": "multi",
        "objectives": request.objectives,
        "recommended": pareto[recommended_index],
        "pareto": pareto,
        "evaluations": request.generations * request.population_size,
        "success": True,
    }
