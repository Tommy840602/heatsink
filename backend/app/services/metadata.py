from pathlib import Path
import math
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal, init_db
from app.db.tables import (
    ExperimentRecord,
    ModelRecord,
    OptimizationRecord,
    ProjectRecord,
    SimulationRecord,
)
from app.repositories.artifacts import ArtifactRepository


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _valid_project_id(session, project_id: str | None) -> str | None:
    if project_id and session.get(ProjectRecord, project_id) is not None:
        return project_id
    return None


def persist_workflow_metadata(
    *,
    project_id: str | None,
    method: str,
    seed: int,
    noise_std: float,
    simulator_version: str,
    dataset_version: str,
    model_id: str,
    model_metrics: dict[str, Any],
    optimization: dict[str, Any],
    traceability: dict[str, Any],
    repository: ArtifactRepository,
) -> None:
    """Persist searchable metadata; large numerical arrays remain in Parquet."""
    init_db()
    with SessionLocal() as session:
        resolved_project = _valid_project_id(session, project_id)
        if resolved_project:
            repository.publish_project_view(
                resolved_project,
                dataset_version,
                model_id,
                dataset_kind="simulation",
            )
        experiment_exists = session.scalar(
            select(ExperimentRecord.id).where(
                ExperimentRecord.dataset_version == dataset_version
            )
        )
        if experiment_exists is None:
            session.add(
                ExperimentRecord(
                    project_id=resolved_project,
                    dataset_version=dataset_version,
                    method=method,
                    seed=seed,
                    run_count=int(traceability.get("experiment_count", 0)),
                    noise_std=noise_std,
                    simulator_version=simulator_version,
                    metadata_json=traceability,
                )
            )
        simulation_exists = session.scalar(
            select(SimulationRecord.id).where(
                SimulationRecord.dataset_version == dataset_version
            )
        )
        if simulation_exists is None:
            session.add(
                SimulationRecord(
                    project_id=resolved_project,
                    dataset_version=dataset_version,
                    simulator_version=simulator_version,
                    seed=seed,
                    noise_std=noise_std,
                    run_count=int(traceability.get("experiment_count", 0)),
                    result_kind="physics_model",
                    metadata_json={
                        "physics_result_is_cfd": False,
                        "feature_definition": traceability.get("feature_definition", []),
                    },
                )
            )
        if session.get(ModelRecord, model_id) is None:
            metadata = repository.load_metadata(model_id)
            session.add(
                ModelRecord(
                    id=model_id,
                    project_id=resolved_project,
                    dataset_version=dataset_version,
                    artifact_path=str(Path("models") / model_id / "bundle.joblib"),
                    metrics=_json_safe(model_metrics),
                    hyperparameters=_json_safe(metadata.get("hyperparameters", {})),
                )
            )
        optimization_id = repository.version(
            {
                "model_id": model_id,
                "dataset_version": dataset_version,
                "optimization": optimization,
            },
            "optimization",
        )
        if session.get(OptimizationRecord, optimization_id) is None:
            session.add(
                OptimizationRecord(
                    id=optimization_id,
                    project_id=resolved_project,
                    model_id=model_id,
                    objectives=list(optimization.get("objectives", [])),
                    constraints=traceability.get("constraints", {}),
                    result=_json_safe(optimization),
                )
            )
        session.commit()
