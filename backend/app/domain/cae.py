from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import DesignParameters


class OpenFoamCaseRequest(BaseModel):
    design: DesignParameters
    heat_load_w: float = Field(default=100.0, gt=0.0, le=1000.0)
    ambient_temperature_c: float = Field(default=25.0, ge=-40.0, le=80.0)
    run_solver: bool = False
    solver: Literal["chtMultiRegionFoam"] = "chtMultiRegionFoam"
    max_runtime_seconds: int = Field(default=900, ge=30, le=7200)


class CaeAcceptanceCriteria(BaseModel):
    max_non_orthogonality: float = Field(default=65.0, gt=0.0, le=90.0)
    max_skewness: float = Field(default=4.0, gt=0.0, le=100.0)
    max_final_residual: float = Field(default=1e-4, gt=0.0, le=0.1)
    max_energy_imbalance_percent: float = Field(default=5.0, gt=0.0, le=50.0)
    max_concave_cell_percent: float = Field(default=5.0, ge=0.0, le=25.0)
    max_low_determinant_cell_percent: float = Field(default=0.0, ge=0.0, le=10.0)
    min_residual_samples: int = Field(default=3, ge=1, le=1000)


class OpenFoamBenchmarkRequest(BaseModel):
    tutorial: Literal["multiRegionHeater"] = "multiRegionHeater"
    max_runtime_seconds: int = Field(default=1800, ge=30, le=7200)
    criteria: CaeAcceptanceCriteria = Field(default_factory=CaeAcceptanceCriteria)


class OpenFoamMeshRequest(BaseModel):
    design: DesignParameters
    max_runtime_seconds: int = Field(default=1800, ge=30, le=7200)
    criteria: CaeAcceptanceCriteria = Field(default_factory=CaeAcceptanceCriteria)


class OpenFoamSmokeRequest(BaseModel):
    design: DesignParameters
    heat_load_w: float = Field(default=100.0, gt=0.0, le=1000.0)
    ambient_temperature_c: float = Field(default=25.0, ge=-40.0, le=80.0)
    max_runtime_seconds: int = Field(default=1800, ge=30, le=7200)
    criteria: CaeAcceptanceCriteria = Field(default_factory=CaeAcceptanceCriteria)
