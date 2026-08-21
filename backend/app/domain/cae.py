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
