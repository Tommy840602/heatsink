import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.domain.phase2 import (
    BayesianProposalRequest,
    CadGenerationRequest,
    Phase2WorkflowRequest,
)
from app.repositories.artifacts import ArtifactRepository
from app.services.bayesian import propose
from app.services.cad import generate_cad
from app.domain.jobs import JobSnapshot
from app.services.jobs import JobQueue, get_job_queue


router = APIRouter(prefix="/api/v1")
repository = ArtifactRepository()


@router.post("/bayesian/propose")
def bayesian_proposal(request: BayesianProposalRequest) -> dict[str, Any]:
    try:
        return propose(request, repository)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dataset or model artifact not found") from exc


@router.post("/cad/generate")
def cad_generation(request: CadGenerationRequest) -> dict[str, Any]:
    try:
        return generate_cad(request, repository)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cad/{cad_id}/artifacts/{filename}")
def cad_artifact(cad_id: str, filename: str) -> FileResponse:
    try:
        path = repository.cad_artifact_path(cad_id, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAD artifact not found") from exc
    return FileResponse(path, filename=filename)


@router.get("/cad/{cad_id}")
def cad_metadata(cad_id: str) -> dict[str, Any]:
    try:
        path = repository.cad_artifact_path(cad_id, "metadata.json")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAD artifact not found") from exc
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/workflows/phase2/run", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def phase2_workflow(request: Phase2WorkflowRequest, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    return JobSnapshot(**queue.enqueue("phase2", request.model_dump(mode="json")))
