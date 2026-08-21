from typing import Any

from fastapi import APIRouter, HTTPException

from app.domain.phase1 import (
    AnalysisRequest,
    ModelPredictionRequest,
    OptimizationRequest,
    Phase1WorkflowRequest,
    Phase1WorkflowResponse,
    TrainingRequest,
)
from app.repositories.artifacts import ArtifactRepository
from app.services.analysis import analyze
from app.services.optimization import optimize
from app.services.surrogates import predict_design, train_surrogates
from app.services.workflow import run_phase1


router = APIRouter(prefix="/api/v1")
repository = ArtifactRepository()


@router.post("/analysis/run")
def run_analysis(request: AnalysisRequest) -> dict[str, Any]:
    return analyze(request.records, request.response)


@router.post("/models/train")
def train_models(request: TrainingRequest) -> dict[str, Any]:
    model_id, metrics, selected = train_surrogates(request.records, request.seed, repository)
    return {"model_id": model_id, "metrics": metrics, "selected_models": selected}


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


@router.post("/optimizations/run")
def run_optimization(request: OptimizationRequest) -> dict[str, Any]:
    try:
        return optimize(request, repository)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Model artifact not found") from exc


@router.post("/workflows/phase1/run", response_model=Phase1WorkflowResponse)
def phase1_workflow(request: Phase1WorkflowRequest) -> Phase1WorkflowResponse:
    return Phase1WorkflowResponse(**run_phase1(request, repository))
