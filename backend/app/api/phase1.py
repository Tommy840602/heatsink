from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.domain.phase1 import (
    AnalysisRequest,
    ModelPredictionRequest,
    ResponseSurfaceRequest,
    OptimizationRequest,
    Phase1WorkflowRequest,
    TrainingRequest,
)
from app.repositories.artifacts import ArtifactRepository
from app.services.analysis import analyze
from app.services.surrogates import predict_design
from app.services.surrogates import predict_bundle, predict_gpr
from app.domain.phase1 import FEATURES
import numpy as np
from app.domain.jobs import JobSnapshot
from app.services.jobs import JobQueue, get_job_queue


router = APIRouter(prefix="/api/v1")
repository = ArtifactRepository()


@router.post("/analysis/run")
def run_analysis(request: AnalysisRequest) -> dict[str, Any]:
    return analyze(request.records, request.response)


@router.post("/models/train", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def train_models(request: TrainingRequest, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    return JobSnapshot(**queue.enqueue("training", request.model_dump(mode="json")))


@router.get("/models/{model_id}/metrics")
def model_metrics(model_id: str) -> dict[str, Any]:
    try:
        return repository.load_metadata(model_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Model artifact not found") from exc


@router.post("/models/{model_id}/predict")
def model_predict(model_id: str, request: ModelPredictionRequest) -> dict[str, Any]:
    try:
        bundle = repository.load_model(model_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Model artifact not found") from exc
    return predict_design(bundle, request.design.model_dump())


@router.post("/models/{model_id}/surface")
def model_surface(model_id: str, request: ResponseSurfaceRequest) -> dict[str, Any]:
    if request.x_axis == request.y_axis:
        raise HTTPException(status_code=422, detail="Surface axes must be different")
    try:
        bundle = repository.load_model(model_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Model artifact not found") from exc
    bounds = {
        "fin_count": (20.0, 60.0),
        "fin_thickness": (0.3, 1.0),
        "fin_height": (20.0, 60.0),
        "fin_spacing": (1.0, 4.0),
        "air_velocity": (0.5, 5.0),
    }
    x_values = np.linspace(*bounds[request.x_axis], request.resolution)
    y_values = np.linspace(*bounds[request.y_axis], request.resolution)
    fixed = request.fixed_design.model_dump()
    rows = []
    for y_value in y_values:
        for x_value in x_values:
            design = dict(fixed)
            design[request.x_axis] = round(x_value) if request.x_axis == "fin_count" else x_value
            design[request.y_axis] = round(y_value) if request.y_axis == "fin_count" else y_value
            rows.append([float(design[name]) for name in FEATURES])
    matrix = np.asarray(rows, dtype=float)
    predictions = predict_bundle(bundle, matrix)
    z_values = predictions[request.response]
    uncertainty = None
    if request.response in bundle["responses"]:
        _, std = predict_gpr(bundle, request.response, matrix)
        uncertainty = std.reshape(request.resolution, request.resolution).round(6).tolist()
    feasible = (predictions["t_max"] <= 80.0) & (predictions["pressure_drop"] <= 35.0)
    candidate_scores = np.where(feasible, z_values, np.inf)
    best_index = int(np.argmin(candidate_scores if np.isfinite(candidate_scores).any() else z_values))
    best_row = matrix[best_index]
    return {
        "model_id": model_id,
        "x_axis": request.x_axis,
        "y_axis": request.y_axis,
        "response": request.response,
        "fixed_design": fixed,
        "resolution": request.resolution,
        "x": x_values.round(6).tolist(),
        "y": y_values.round(6).tolist(),
        "z": z_values.reshape(request.resolution, request.resolution).round(6).tolist(),
        "uncertainty": uncertainty,
        "current": {
            "design": fixed,
            "responses": predict_design(bundle, fixed),
        },
        "optimal": {
            "design": {
                name: int(best_row[index]) if name == "fin_count" else round(float(best_row[index]), 6)
                for index, name in enumerate(FEATURES)
            },
            "responses": {
                name: round(float(values[best_index]), 6)
                for name, values in predictions.items()
            },
        },
    }


@router.post("/optimizations/run", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def run_optimization(request: OptimizationRequest, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    return JobSnapshot(**queue.enqueue("optimization", request.model_dump(mode="json")))


@router.post("/workflows/phase1/run", response_model=JobSnapshot, status_code=status.HTTP_202_ACCEPTED)
def phase1_workflow(request: Phase1WorkflowRequest, queue: JobQueue = Depends(get_job_queue)) -> JobSnapshot:
    return JobSnapshot(**queue.enqueue("phase1", request.model_dump(mode="json")))
