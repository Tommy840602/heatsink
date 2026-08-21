from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.domain.phase2 import (
    BayesianProposalRequest,
    CadGenerationRequest,
    Phase2WorkflowRequest,
    Phase2WorkflowResponse,
)
from app.repositories.artifacts import ArtifactRepository
from app.services.bayesian import propose
from app.services.cad import generate_cad
from app.services.phase2_workflow import run_phase2


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


@router.post("/workflows/phase2/run", response_model=Phase2WorkflowResponse)
def phase2_workflow(request: Phase2WorkflowRequest) -> Phase2WorkflowResponse:
    try:
        return Phase2WorkflowResponse(**run_phase2(request, repository))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Dataset or model artifact not found") from exc
