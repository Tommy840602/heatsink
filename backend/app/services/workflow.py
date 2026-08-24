from datetime import UTC, datetime
from typing import Any

from app.domain.models import DesignParameters, DoeRequest
from app.domain.phase1 import OptimizationRequest, Phase1WorkflowRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.analysis import analyze
from app.services.doe import generate_doe
from app.services.optimization import optimize
from app.services.simulator import SIMULATOR_VERSION, simulate
from app.services.surrogates import train_surrogates
from app.services.metadata import persist_workflow_metadata
import os


def run_phase1(request: Phase1WorkflowRequest, repository: ArtifactRepository | None = None) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    factors, matrix = generate_doe(
        DoeRequest(
            method=request.method,
            runs=request.runs,
            seed=request.seed,
            factors=request.factors,
        )
    )
    records: list[dict[str, Any]] = []
    for index, parameters in enumerate(matrix):
        design = DesignParameters(**parameters)
        result = simulate(design, noise_std=request.noise_std, seed=request.seed + index)
        records.append({"run": index + 1, **parameters, **result.model_dump()})

    dataset_version = repository.save_dataset(records)
    analysis = analyze(records, request.response_for_analysis)
    model_id, model_metrics, selected_models = train_surrogates(records, request.seed, repository)
    optimization = optimize(
        OptimizationRequest(
            model_id=model_id,
            mode="multi",
            objectives=request.optimization_objectives,
            t_max_limit=request.t_max_limit,
            pressure_drop_limit=request.pressure_drop_limit,
            mass_limit=request.mass_limit,
            seed=request.seed,
            generations=request.optimization_generations,
            population_size=48,
            factors=factors,
        ),
        repository,
    )
    fingerprint = {
        "dataset": dataset_version,
        "model": model_id,
        "method": request.method,
        "seed": request.seed,
    }
    workflow_id = repository.version(fingerprint, "workflow")
    traceability = {
        **fingerprint,
        "noise_std": request.noise_std,
        "experiment_count": len(records),
        "feature_definition": [
            factor.model_dump() for factor in factors
        ],
        "objectives": request.optimization_objectives,
        "constraints": {
            "t_max_limit": request.t_max_limit,
            "pressure_drop_limit": request.pressure_drop_limit,
            "mass_limit": request.mass_limit,
        },
        "simulator_version": SIMULATOR_VERSION,
        "code_version": os.getenv("THERMOFORM_GIT_COMMIT", "development"),
        "completed_at": datetime.now(UTC).isoformat(),
        "physics_result_is_cfd": False,
    }
    result = {
        "workflow_id": workflow_id,
        "status": "completed",
        "method": request.method,
        "seed": request.seed,
        "experiment_count": len(records),
        "experiments": records,
        "analysis": analysis,
        "model_id": model_id,
        "model_metrics": model_metrics,
        "selected_models": selected_models,
        "optimization": optimization,
        "dataset_version": dataset_version,
        "model_version": model_id,
        "simulator_version": SIMULATOR_VERSION,
        "traceability": traceability,
    }
    persist_workflow_metadata(
        project_id=request.project_id,
        method=request.method,
        seed=request.seed,
        noise_std=request.noise_std,
        simulator_version=SIMULATOR_VERSION,
        dataset_version=dataset_version,
        model_id=model_id,
        model_metrics=model_metrics,
        optimization=optimization,
        traceability=traceability,
        repository=repository,
    )
    return result
