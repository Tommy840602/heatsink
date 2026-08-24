from typing import Any

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.problem import ElementwiseProblem
from pymoo.optimize import minimize as pymoo_minimize
from scipy.optimize import differential_evolution, minimize as scipy_minimize

from app.domain.phase1 import FEATURES, OptimizationRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.surrogates import predict_bundle


LOWER = np.asarray([20.0, 0.3, 20.0, 1.0, 0.5])
UPPER = np.asarray([60.0, 1.0, 60.0, 4.0, 5.0])


def _request_bounds(request: OptimizationRequest) -> tuple[np.ndarray, np.ndarray]:
    if not request.factors:
        return LOWER, UPPER
    configured = {factor.name: factor for factor in request.factors}
    if set(configured) != set(FEATURES):
        raise ValueError("Optimization factors must define all five canonical features")
    return (
        np.asarray([configured[name].lower for name in FEATURES], dtype=float),
        np.asarray([configured[name].upper for name in FEATURES], dtype=float),
    )


def _physical_row(
    vector: np.ndarray,
    lower: np.ndarray = LOWER,
    upper: np.ndarray = UPPER,
) -> np.ndarray:
    row = np.clip(np.asarray(vector, dtype=float), lower, upper)
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
        self.lower, self.upper = _request_bounds(request)
        super().__init__(n_var=len(FEATURES), n_obj=len(request.objectives), n_ieq_constr=3 if request.mass_limit is not None else 2, xl=self.lower, xu=self.upper)
        self.bundle = bundle
        self.request = request

    def _evaluate(self, x, out, *args, **kwargs):
        row = _physical_row(x, self.lower, self.upper)
        predicted = _predict(self.bundle, row)
        out["F"] = [predicted[name] for name in self.request.objectives]
        constraints = [
            predicted["t_max"] - self.request.t_max_limit,
            predicted["pressure_drop"] - self.request.pressure_drop_limit,
        ]
        if self.request.mass_limit is not None:
            constraints.append(predicted["mass"] - self.request.mass_limit)
        out["G"] = constraints


def optimize(request: OptimizationRequest, repository: ArtifactRepository | None = None) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    bundle = repository.load_model(request.model_id)
    lower, upper = _request_bounds(request)

    if request.mode == "single":
        objective = request.objectives[0]

        def score(vector: np.ndarray) -> float:
            row = _physical_row(vector, lower, upper)
            predicted = _predict(bundle, row)
            penalty = max(predicted["t_max"] - request.t_max_limit, 0.0) * 1e3
            penalty += max(predicted["pressure_drop"] - request.pressure_drop_limit, 0.0) * 1e3
            if request.mass_limit is not None:
                penalty += max(predicted["mass"] - request.mass_limit, 0.0) * 1e3
            return predicted[objective] + penalty

        bounds = list(zip(lower, upper, strict=True))
        global_result = None
        if request.algorithm in {"auto", "differential_evolution"}:
            global_result = differential_evolution(
                score,
                bounds=bounds,
                seed=request.seed,
                maxiter=request.generations,
                popsize=max(5, request.population_size // len(FEATURES)),
                polish=request.algorithm == "differential_evolution",
                workers=1,
            )

        local_result = None
        if request.algorithm in {"auto", "slsqp"}:
            start = global_result.x if global_result is not None else (lower + upper) / 2.0

            def thermal_constraint(vector: np.ndarray) -> float:
                return request.t_max_limit - _predict(bundle, _physical_row(vector, lower, upper))["t_max"]

            def pressure_constraint(vector: np.ndarray) -> float:
                return request.pressure_drop_limit - _predict(bundle, _physical_row(vector, lower, upper))["pressure_drop"]

            constraints = [
                {"type": "ineq", "fun": thermal_constraint},
                {"type": "ineq", "fun": pressure_constraint},
            ]
            if request.mass_limit is not None:
                constraints.append(
                    {
                        "type": "ineq",
                        "fun": lambda vector: request.mass_limit
                        - _predict(bundle, _physical_row(vector, lower, upper))["mass"],
                    }
                )

            local_result = scipy_minimize(
                lambda vector: _predict(bundle, _physical_row(vector, lower, upper))[objective],
                start,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"maxiter": max(100, request.generations * 5), "ftol": 1e-9},
            )

        candidates = [result for result in (global_result, local_result) if result is not None]
        feasible_candidates = []
        for candidate in candidates:
            candidate_row = _physical_row(candidate.x, lower, upper)
            candidate_prediction = _predict(bundle, candidate_row)
            if (
                candidate_prediction["t_max"] <= request.t_max_limit + 1e-6
                and candidate_prediction["pressure_drop"] <= request.pressure_drop_limit + 1e-6
                and (
                    request.mass_limit is None
                    or candidate_prediction["mass"] <= request.mass_limit + 1e-6
                )
            ):
                feasible_candidates.append(candidate)
        result = min(feasible_candidates or candidates, key=lambda candidate: score(candidate.x))
        row = _physical_row(result.x, lower, upper)
        predicted = _predict(bundle, row)
        return {
            "mode": "single",
            "objectives": request.objectives,
            "recommended": {"design": _design(row), "responses": predicted},
            "pareto": [],
            "evaluations": int(result.nfev),
            "success": bool(result.success),
            "algorithm": (
                "differential_evolution+slsqp"
                if request.algorithm == "auto"
                else request.algorithm
            ),
        }

    problem = SurrogateOptimizationProblem(bundle, request)
    algorithm = NSGA2(pop_size=request.population_size, eliminate_duplicates=True)
    result = pymoo_minimize(
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
