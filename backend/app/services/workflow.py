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


def run_phase1(request: Phase1WorkflowRequest, repository: ArtifactRepository | None = None) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    _, matrix = generate_doe(DoeRequest(method=request.method, runs=request.runs, seed=request.seed))
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
            objectives=["t_max", "pressure_drop", "mass"],
            seed=request.seed,
            generations=request.optimization_generations,
            population_size=48,
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
    return {
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
        "traceability": {
            **fingerprint,
            "noise_std": request.noise_std,
            "feature_definition": [
                "fin_count",
                "fin_thickness",
                "fin_height",
                "fin_spacing",
                "air_velocity",
            ],
            "completed_at": datetime.now(UTC).isoformat(),
            "physics_result_is_cfd": False,
        },
    }
