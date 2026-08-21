from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DesignParameters(BaseModel):
    fin_count: int = Field(ge=20, le=60)
    fin_thickness: float = Field(ge=0.3, le=1.0, description="Millimetres")
    fin_height: float = Field(ge=20.0, le=60.0, description="Millimetres")
    fin_spacing: float = Field(ge=1.0, le=4.0, description="Millimetres")
    air_velocity: float = Field(ge=0.5, le=5.0, description="Metres per second")
    heat_load: float = Field(default=100.0, gt=0, le=500.0, description="Watts")
    ambient_temperature: float = Field(default=25.0, ge=-20.0, le=60.0)


class SimulationResult(BaseModel):
    t_max: float
    thermal_resistance: float
    pressure_drop: float
    mass: float
    fin_efficiency: float
    heat_transfer_coefficient: float
    simulator_version: str = "1.0.0"


class FactorRange(BaseModel):
    name: Literal[
        "fin_count", "fin_thickness", "fin_height", "fin_spacing", "air_velocity"
    ]
    lower: float
    upper: float
    integer: bool = False

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.lower >= self.upper:
            raise ValueError("lower must be smaller than upper")
        return self


class DoeRequest(BaseModel):
    method: Literal["LHS", "CCD", "BBD"] = "LHS"
    runs: int = Field(default=64, ge=30, le=100)
    seed: int = Field(default=42, ge=0)
    factors: list[FactorRange] | None = None


class DoeResponse(BaseModel):
    method: str
    seed: int
    runs: int
    factors: list[str]
    matrix: list[dict[str, float | int]]
    dataset_version: str = "v13"


class BatchSimulationRequest(BaseModel):
    designs: list[DesignParameters] = Field(min_length=1, max_length=100)
    noise_std: float = Field(default=0.0, ge=0.0, le=5.0)
    seed: int = Field(default=42, ge=0)


class BatchSimulationResponse(BaseModel):
    count: int
    results: list[SimulationResult]
    seed: int
    deterministic: bool
