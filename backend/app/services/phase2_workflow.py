from datetime import UTC, datetime
import os
from typing import Any

from app.domain.models import DesignParameters
from app.domain.phase1 import RESPONSES
from app.domain.phase2 import (
    BayesianProposalRequest,
    CadGenerationRequest,
    Phase2WorkflowRequest,
)
from app.repositories.artifacts import ArtifactRepository
from app.services.bayesian import propose
from app.services.cad import generate_cad
from app.services.simulator import SIMULATOR_VERSION, simulate
from app.services.surrogates import records_to_xy, train_surrogates
from app.services.metadata import persist_workflow_metadata


def _refit_gprs(bundle: dict[str, Any], records: list[dict[str, Any]]) -> None:
    for response in RESPONSES:
        x, y = records_to_xy(records, response)
        bundle["responses"][response]["models"]["GPR"].fit(x, y)


def run_phase2(
    request: Phase2WorkflowRequest, repository: ArtifactRepository | None = None
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    records = repository.load_dataset(request.dataset_version)
    bundle = repository.load_model(request.model_id)
    proposals: list[dict[str, Any]] = []

    for iteration in range(request.iterations):
        proposal_result = propose(
            BayesianProposalRequest(
                model_id=request.model_id,
                dataset_version=request.dataset_version,
                acquisition=request.acquisition,
                batch_size=1,
                seed=request.seed + iteration,
            ),
            repository,
            bundle=bundle,
            records=records,
        )
        proposal = proposal_result["proposals"][0]
        design = DesignParameters(**proposal["design"])
        simulation = simulate(design, noise_std=request.noise_std, seed=request.seed + iteration)
        record = {
            "run": len(records) + 1,
            **proposal["design"],
            **simulation.model_dump(),
        }
        records.append(record)
        proposals.append(
            {
                "iteration": iteration + 1,
                **proposal,
                "simulated_responses": {
                    name: record[name] for name in RESPONSES
                },
                "simulator_version": SIMULATOR_VERSION,
            }
        )
        _refit_gprs(bundle, records)

    dataset_version = repository.save_dataset(records)
    model_id, metrics, selected = train_surrogates(records, request.seed, repository)
    feasible = [
        row
        for row in records
        if float(row["t_max"]) < 80.0 and float(row["pressure_drop"]) < 35.0
    ]
    best = min(feasible or records, key=lambda row: float(row["t_max"]))
    best_design = {
        name: best[name]
        for name in ("fin_count", "fin_thickness", "fin_height", "fin_spacing", "air_velocity")
    }
    best_response = {name: best[name] for name in RESPONSES}
    cad = (
        generate_cad(CadGenerationRequest(design=DesignParameters(**best_design)), repository)
        if request.generate_cad
        else None
    )
    fingerprint = {
        "source_dataset": request.dataset_version,
        "source_model": request.model_id,
        "dataset": dataset_version,
        "model": model_id,
        "acquisition": request.acquisition,
        "iterations": request.iterations,
        "seed": request.seed,
    }
    traceability = {
        **fingerprint,
        "experiment_count": len(records),
        "noise_std": request.noise_std,
        "objectives": ["t_max"],
        "constraints": {"t_max_limit": 80.0, "pressure_drop_limit": 35.0},
        "simulator_version": SIMULATOR_VERSION,
        "code_version": os.getenv("THERMOFORM_GIT_COMMIT", "development"),
        "completed_at": datetime.now(UTC).isoformat(),
        "physics_result_is_cfd": False,
        "cad_step_requires_freecad": True,
    }
    result = {
        "workflow_id": repository.version(fingerprint, "phase2"),
        "status": "completed",
        "acquisition": request.acquisition,
        "iterations": request.iterations,
        "proposals": proposals,
        "experiment_count": len(records),
        "dataset_version": dataset_version,
        "model_id": model_id,
        "model_metrics": metrics,
        "selected_models": selected,
        "best_design": best_design,
        "best_response": best_response,
        "cad": cad,
        "traceability": traceability,
    }
    persist_workflow_metadata(
        project_id=request.project_id,
        method=f"Bayesian Optimization ({request.acquisition})",
        seed=request.seed,
        noise_std=request.noise_std,
        simulator_version=SIMULATOR_VERSION,
        dataset_version=dataset_version,
        model_id=model_id,
        model_metrics=metrics,
        optimization={
            "mode": "bayesian",
            "objectives": ["t_max"],
            "recommended": {"design": best_design, "responses": best_response},
            "pareto": [],
            "acquisition": request.acquisition,
        },
        traceability=traceability,
        repository=repository,
    )
    return result
