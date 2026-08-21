from typing import Any

from app.domain.cae import OpenFoamCaseRequest
from app.domain.phase1 import Phase1WorkflowRequest
from app.domain.phase2 import Phase2WorkflowRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam import prepare_openfoam_case
from app.services.phase2_workflow import run_phase2
from app.services.workflow import run_phase1


def execute_job(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    """RQ entrypoint. Validation is intentionally repeated inside the worker process."""
    repository = ArtifactRepository()
    if task == "phase1":
        return run_phase1(Phase1WorkflowRequest.model_validate(payload), repository)
    if task == "phase2":
        return run_phase2(Phase2WorkflowRequest.model_validate(payload), repository)
    if task == "cae":
        return prepare_openfoam_case(OpenFoamCaseRequest.model_validate(payload), repository)
    raise ValueError(f"Unsupported job task: {task}")
