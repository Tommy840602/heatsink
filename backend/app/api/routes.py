import os

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from redis import Redis

from app.domain.models import (
    BatchSimulationRequest,
    DesignParameters,
    DoeRequest,
    SimulationResult,
)
from app.services.simulator import SIMULATOR_VERSION, simulate
from app.db.session import get_db
from app.db.tables import DesignRecord, ExperimentRecord, ModelRecord, ProjectRecord
from app.domain.jobs import JobSnapshot
from app.services.jobs import JobQueue, get_job_queue


router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "thermoform-api", "simulator_version": SIMULATOR_VERSION}


@router.get("/health/live")
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)) -> dict[str, object]:
    db.execute(select(1))
    redis_url = os.getenv("THERMOFORM_REDIS_URL")
    redis_ready = True
    if redis_url:
        redis_ready = bool(Redis.from_url(redis_url, socket_timeout=1).ping())
    return {"status": "ready", "database": True, "redis": redis_ready}


@router.get("/overview")
def overview(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    project = db.get(ProjectRecord, project_id) if project_id else db.scalar(
        select(ProjectRecord).where(ProjectRecord.status == "active").order_by(ProjectRecord.created_at.desc())
    )
    resolved_id = project.id if project else None
    experiment_filter = ExperimentRecord.project_id == resolved_id if resolved_id else ExperimentRecord.project_id.is_(None)
    experiments = int(db.scalar(select(func.coalesce(func.sum(ExperimentRecord.run_count), 0)).where(experiment_filter)) or 0)
    model_filter = ModelRecord.project_id == resolved_id if resolved_id else ModelRecord.project_id.is_(None)
    model = db.scalar(select(ModelRecord).where(model_filter).order_by(ModelRecord.created_at.desc()))
    design = db.scalar(
        select(DesignRecord).where(DesignRecord.project_id == resolved_id).order_by(DesignRecord.created_at.desc())
    ) if resolved_id else None
    simulation = simulate(DesignParameters(**design.parameters)) if design else None
    best_model = None
    if model:
        t_max_metrics = model.metrics.get("t_max", [])
        if t_max_metrics:
            best_model = min(t_max_metrics, key=lambda row: row.get("cv_rmse", float("inf"))).get("model")
    return {
        "project_id": resolved_id,
        "project_status": project.status if project else "not_created",
        "experiments": experiments,
        "best_model": best_model,
        "best_design": design.parameters if design else None,
        "current_t_max": simulation.t_max if simulation else None,
        "current_mass": simulation.mass if simulation else None,
        "dataset_version": model.dataset_version if model else None,
        "model_id": model.id if model else None,
    }


@router.post("/designs/validate")
def validate_design(design: DesignParameters) -> dict[str, object]:
    return {"valid": True, "design": design.model_dump(), "bounds_version": "v1"}


@router.post("/doe/generate", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def doe(request: DoeRequest, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    return JobSnapshot(**queue.enqueue("doe", request.model_dump(mode="json")))


@router.post("/simulations/predict", response_model=SimulationResult)
def predict(design: DesignParameters) -> SimulationResult:
    return simulate(design)


@router.post("/simulations/run", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def run_batch(request: BatchSimulationRequest, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    return JobSnapshot(**queue.enqueue("simulation", request.model_dump(mode="json")))
