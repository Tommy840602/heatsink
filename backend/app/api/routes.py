from fastapi import APIRouter

from app.domain.models import (
    BatchSimulationRequest,
    BatchSimulationResponse,
    DesignParameters,
    DoeRequest,
    DoeResponse,
    SimulationResult,
)
from app.services.doe import generate_doe
from app.services.simulator import SIMULATOR_VERSION, simulate


router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "thermoform-api", "simulator_version": SIMULATOR_VERSION}


@router.get("/overview")
def overview() -> dict[str, object]:
    return {
        "experiments": 64,
        "best_model": "GPR",
        "best_t_max": 68.4,
        "estimated_mass": 287,
        "dataset_version": "v12",
    }


@router.post("/designs/validate")
def validate_design(design: DesignParameters) -> dict[str, object]:
    return {"valid": True, "design": design.model_dump(), "bounds_version": "v1"}


@router.post("/doe/generate", response_model=DoeResponse)
def doe(request: DoeRequest) -> DoeResponse:
    factors, matrix = generate_doe(request)
    return DoeResponse(
        method=request.method,
        seed=request.seed,
        runs=len(matrix),
        factors=[factor.name for factor in factors],
        matrix=matrix,
    )


@router.post("/simulations/predict", response_model=SimulationResult)
def predict(design: DesignParameters) -> SimulationResult:
    return simulate(design)


@router.post("/simulations/run", response_model=BatchSimulationResponse)
def run_batch(request: BatchSimulationRequest) -> BatchSimulationResponse:
    results = [simulate(design, request.noise_std, request.seed + index) for index, design in enumerate(request.designs)]
    return BatchSimulationResponse(
        count=len(results),
        results=results,
        seed=request.seed,
        deterministic=request.noise_std == 0,
    )
