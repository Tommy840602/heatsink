from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from redis.exceptions import RedisError

from app.domain.cae import OpenFoamCampaignRequest, OpenFoamCaseRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam import prepare_openfoam_case
from app.services.jobs import CAE_QUEUE_NAME, JobQueue, get_job_queue
from app.services.openfoam_benchmark import OPENFOAM_TARGET, TUTORIAL_RELATIVE_PATH
from app.services.cae_history import (
    list_campaign_reports,
    list_mesh_study_reports,
    list_resume_dispatches,
    load_campaign_report,
    load_mesh_study_report,
)
from app.services.cae_resume import (
    enqueue_campaign_resume,
    preview_campaign_resume,
    retry_campaign_resume,
)


router = APIRouter(prefix="/api/v1")
repository = ArtifactRepository()


@router.get("/cae/runtime-requirements")
def runtime_requirements() -> dict[str, Any]:
    return {
        "target_distribution": OPENFOAM_TARGET,
        "architecture": "linux/amd64",
        "queue": CAE_QUEUE_NAME,
        "queue_tasks": ["cae", "cae_mesh", "cae_smoke", "cae_solve", "cae_campaign", "cae_mesh_study", "cae_benchmark"],
        "tutorial": str(TUTORIAL_RELATIVE_PATH),
        "worker_profile": "cae",
        "package_source": "https://dl.openfoam.com/repos/deb/",
        "result_policy": "A runtime benchmark never becomes a heat-sink CFD result.",
        "mesh_policy": "A design mesh must pass watertight geometry, region-interface, and per-region quality gates before thermal fields are enabled.",
        "smoke_policy": "A one-step CHT run validates fields, materials, heat source, and solver startup only; it never becomes a design response.",
        "response_policy": "Responses require at least five stable samples, residual convergence, energy balance, and a non-smoke result mode.",
        "solve_policy": "Production CHT runs use immutable checkpoints, may resume only the same case fingerprint, and publish responses only after every numerical gate passes.",
        "campaign_policy": "Campaigns chain production checkpoints until convergence, cancellation, target time, segment limit, or runtime budget; cancellation is cooperative at checkpoint boundaries.",
        "mesh_independence_policy": "A publishable design result requires converged coarse, medium, and fine campaigns plus medium-to-fine Tmax and pressure-drop changes within configured limits.",
    }


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


@router.get("/cae/campaigns")
def campaigns(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    reports = list_campaign_reports(repository, limit)
    return {"campaigns": reports, "count": len(reports)}


@router.get("/cae/resume-attempts")
def resume_attempts(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, Any]:
    reports = list_resume_dispatches(repository, limit)
    return {"resume_attempts": reports, "count": len(reports)}


@router.get("/cae/campaigns/{campaign_id}")
def campaign(campaign_id: str) -> dict[str, Any]:
    try:
        return load_campaign_report(repository, campaign_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAE campaign not found") from exc


@router.post("/cae/campaigns/{campaign_id}/resume-preview")
def campaign_resume_preview(
    campaign_id: str, request: OpenFoamCampaignRequest
) -> dict[str, Any]:
    try:
        return preview_campaign_resume(campaign_id, request, repository)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAE campaign not found") from exc


@router.post("/cae/campaigns/{campaign_id}/resume")
def campaign_resume(
    campaign_id: str,
    request: OpenFoamCampaignRequest,
    response: Response,
    queue: JobQueue = Depends(get_job_queue),
) -> dict[str, Any]:
    try:
        result = enqueue_campaign_resume(campaign_id, request, repository, queue)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAE campaign not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Job queue is unavailable") from exc
    if result["resume_ready"] and not result.get("deduplicated"):
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.post("/cae/resume-attempts/{resume_attempt_id}/retry")
def retry_resume_attempt(
    resume_attempt_id: str,
    response: Response,
    queue: JobQueue = Depends(get_job_queue),
) -> dict[str, Any]:
    try:
        result = retry_campaign_resume(resume_attempt_id, repository, queue)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="CAE resume attempt not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Job queue is unavailable") from exc
    if result["resume_ready"] and not result.get("deduplicated"):
        response.status_code = status.HTTP_202_ACCEPTED
    return result


@router.get("/cae/mesh-studies")
def mesh_studies(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    reports = list_mesh_study_reports(repository, limit)
    return {"mesh_studies": reports, "count": len(reports)}


@router.get("/cae/mesh-studies/{mesh_study_id}")
def mesh_study(mesh_study_id: str) -> dict[str, Any]:
    try:
        return load_mesh_study_report(repository, mesh_study_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAE mesh study not found") from exc


@router.get("/cae/{case_id}/artifacts/{filename}")
def cae_artifact(case_id: str, filename: str) -> FileResponse:
    try:
        path = repository.cae_artifact_path(case_id, filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="CAE artifact not found") from exc
    return FileResponse(path, filename=filename)
