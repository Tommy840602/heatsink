from typing import Any

import numpy as np
from scipy import stats
from scipy.stats import qmc

from app.domain.phase1 import FEATURES
from app.domain.phase2 import BayesianProposalRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.optimization import LOWER, UPPER, _design, _physical_row
from app.services.surrogates import predict_bundle, predict_gpr


def _acquisition_values(
    mean: np.ndarray,
    uncertainty: np.ndarray,
    best: float,
    request: BayesianProposalRequest,
) -> np.ndarray:
    sigma = np.maximum(uncertainty, 1e-12)
    improvement = best - mean - request.xi
    z = improvement / sigma
    if request.acquisition == "EI":
        values = improvement * stats.norm.cdf(z) + sigma * stats.norm.pdf(z)
        return np.where(uncertainty > 1e-12, values, 0.0)
    if request.acquisition == "PI":
        return np.where(uncertainty > 1e-12, stats.norm.cdf(z), 0.0)
    # For minimization, maximizing the negative lower confidence bound is the
    # conventional UCB-style exploration score.
    return -(mean - request.kappa * sigma)


def propose(
    request: BayesianProposalRequest,
    repository: ArtifactRepository | None = None,
    bundle: dict[str, Any] | None = None,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    bundle = bundle or repository.load_model(request.model_id)
    records = records or repository.load_dataset(request.dataset_version)

    sampler = qmc.LatinHypercube(d=len(FEATURES), seed=request.seed)
    candidates = qmc.scale(sampler.random(request.candidate_pool_size), LOWER, UPPER)
    candidates[:, 0] = np.rint(candidates[:, 0])
    candidates = np.unique(candidates, axis=0)

    mean, uncertainty = predict_gpr(bundle, request.objective, candidates)
    selected_predictions = predict_bundle(bundle, candidates)
    feasible = (
        selected_predictions["t_max"] <= request.t_max_limit
    ) & (selected_predictions["pressure_drop"] <= request.pressure_drop_limit)

    observed_feasible = [
        float(row[request.objective])
        for row in records
        if float(row["t_max"]) <= request.t_max_limit
        and float(row["pressure_drop"]) <= request.pressure_drop_limit
    ]
    observed = observed_feasible or [float(row[request.objective]) for row in records]
    best = min(observed)
    acquisition = _acquisition_values(mean, uncertainty, best, request)
    acquisition = np.where(feasible, acquisition, -np.inf)
    if not np.isfinite(acquisition).any():
        acquisition = _acquisition_values(mean, uncertainty, best, request)

    ranked = np.argsort(acquisition)[::-1]
    proposals: list[dict[str, Any]] = []
    seen: set[tuple[float, ...]] = set()
    for index in ranked:
        row = _physical_row(candidates[index])
        signature = tuple(row.tolist())
        if signature in seen:
            continue
        seen.add(signature)
        predictions = {
            response: round(float(values[index]), 6)
            for response, values in selected_predictions.items()
        }
        proposals.append(
            {
                "design": _design(row),
                "predicted_responses": predictions,
                "objective_mean": round(float(mean[index]), 6),
                "objective_uncertainty": round(float(uncertainty[index]), 6),
                "acquisition_value": round(float(acquisition[index]), 8),
                "predicted_feasible": bool(feasible[index]),
            }
        )
        if len(proposals) == request.batch_size:
            break

    return {
        "acquisition": request.acquisition,
        "objective": request.objective,
        "best_observed": round(best, 6),
        "candidate_pool_size": len(candidates),
        "proposals": proposals,
        "model_id": request.model_id,
        "dataset_version": request.dataset_version,
    }
