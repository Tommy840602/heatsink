from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.models import DesignParameters


class BayesianProposalRequest(BaseModel):
    model_id: str
    dataset_version: str
    acquisition: Literal["EI", "PI", "UCB"] = "EI"
    objective: Literal["t_max", "thermal_resistance", "pressure_drop", "mass"] = "t_max"
    batch_size: int = Field(default=1, ge=1, le=8)
    candidate_pool_size: int = Field(default=1024, ge=128, le=8192)
    seed: int = Field(default=42, ge=0)
    xi: float = Field(default=0.01, ge=0.0, le=2.0)
    kappa: float = Field(default=2.0, gt=0.0, le=10.0)
    t_max_limit: float = Field(default=80.0, ge=30.0, le=150.0)
    pressure_drop_limit: float = Field(default=35.0, gt=0.0, le=500.0)


class CadGenerationRequest(BaseModel):
    design: DesignParameters
    base_thickness: float = Field(default=4.0, ge=2.0, le=15.0)
    base_width: float | None = Field(default=None, ge=40.0, le=400.0)
    base_length: float = Field(default=90.0, ge=40.0, le=300.0)
    edge_margin: float = Field(default=2.0, ge=0.0, le=20.0)
    material: str = Field(default="Al 6063-T5", min_length=2, max_length=80)


class Phase2WorkflowRequest(BaseModel):
    project_id: str | None = None
    model_id: str
    dataset_version: str
    acquisition: Literal["EI", "PI", "UCB"] = "EI"
    iterations: int = Field(default=3, ge=1, le=8)
    seed: int = Field(default=42, ge=0)
    noise_std: float = Field(default=0.0, ge=0.0, le=5.0)
    generate_cad: bool = True


class Phase2WorkflowResponse(BaseModel):
    workflow_id: str
    status: Literal["completed"] = "completed"
    acquisition: str
    iterations: int
    proposals: list[dict[str, Any]]
    experiment_count: int
    dataset_version: str
    model_id: str
    model_metrics: dict[str, Any]
    selected_models: dict[str, str]
    best_design: dict[str, Any]
    best_response: dict[str, Any]
    cad: dict[str, Any] | None
    traceability: dict[str, Any]
