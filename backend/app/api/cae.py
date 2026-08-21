from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.domain.cae import OpenFoamCaseRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam import prepare_openfoam_case


router = APIRouter(prefix="/api/v1")
repository = ArtifactRepository()


@router.post("/cae/cases")
def create_case(request: OpenFoamCaseRequest) -> dict[str, Any]:
    if request.run_solver:
        raise HTTPException(
            status_code=409,
            detail="Solver execution must be submitted as a CAE job through POST /api/v1/jobs",
        )
    try:
        return prepare_openfoam_case(request, repository)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cae/{case_id}/artifacts/{filename}")
def cae_artifact(case_id: str, filename: str) -> FileResponse:
    try:
        path = repository.cae_artifact_path(case_id, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAE artifact not found") from exc
    return FileResponse(path, filename=filename)
