from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.models import DesignParameters


FEATURES = ["fin_count", "fin_thickness", "fin_height", "fin_spacing", "air_velocity"]
RESPONSES = ["t_max", "thermal_resistance", "pressure_drop", "mass"]


class AnalysisRequest(BaseModel):
    records: list[dict[str, float | int]] = Field(min_length=12)
    response: Literal["t_max", "thermal_resistance", "pressure_drop", "mass"] = "t_max"


class TrainingRequest(BaseModel):
    records: list[dict[str, float | int]] = Field(min_length=20)
    seed: int = Field(default=42, ge=0)


class ModelPredictionRequest(BaseModel):
    design: DesignParameters


class OptimizationRequest(BaseModel):
    model_id: str
    mode: Literal["single", "multi"] = "multi"
    objectives: list[Literal["t_max", "thermal_resistance", "pressure_drop", "mass"]] = Field(
        default_factory=lambda: ["t_max", "pressure_drop", "mass"], min_length=1, max_length=4
    )
    t_max_limit: float = Field(default=80.0, ge=30.0, le=150.0)
    pressure_drop_limit: float = Field(default=35.0, gt=0.0, le=500.0)
    seed: int = Field(default=42, ge=0)
    generations: int = Field(default=30, ge=10, le=200)
    population_size: int = Field(default=48, ge=20, le=200)


class Phase1WorkflowRequest(BaseModel):
    method: Literal["LHS", "CCD", "BBD"] = "LHS"
    runs: int = Field(default=48, ge=30, le=100)
    seed: int = Field(default=42, ge=0)
    noise_std: float = Field(default=0.0, ge=0.0, le=5.0)
    response_for_analysis: Literal[
        "t_max", "thermal_resistance", "pressure_drop", "mass"
    ] = "t_max"
    optimization_generations: int = Field(default=25, ge=10, le=100)


class Phase1WorkflowResponse(BaseModel):
    workflow_id: str
    status: Literal["completed"] = "completed"
    method: str
    seed: int
    experiment_count: int
    experiments: list[dict[str, Any]]
    analysis: dict[str, Any]
    model_id: str
    model_metrics: dict[str, Any]
    selected_models: dict[str, str]
    optimization: dict[str, Any]
    dataset_version: str
    model_version: str
    simulator_version: str
    traceability: dict[str, Any]
