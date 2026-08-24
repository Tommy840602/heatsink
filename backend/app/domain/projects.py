from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.models import DesignParameters


def default_design_space() -> dict[str, dict[str, Any]]:
    return {
        "fin_count": {"lower": 20, "upper": 60, "unit": "-", "integer": True},
        "fin_thickness": {"lower": 0.3, "upper": 1.0, "unit": "mm", "integer": False},
        "fin_height": {"lower": 20.0, "upper": 60.0, "unit": "mm", "integer": False},
        "fin_spacing": {"lower": 1.0, "upper": 4.0, "unit": "mm", "integer": False},
        "air_velocity": {"lower": 0.5, "upper": 5.0, "unit": "m/s", "integer": False},
    }


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    design_space: dict[str, dict[str, Any]] = Field(default_factory=default_design_space)

    @field_validator("design_space")
    @classmethod
    def validate_design_space(cls, value):
        canonical = default_design_space()
        if set(value) != set(canonical):
            raise ValueError("design_space must define the five canonical heat-sink factors")
        for name, configured in value.items():
            lower = float(configured.get("lower"))
            upper = float(configured.get("upper"))
            if lower >= upper:
                raise ValueError(f"{name} lower bound must be smaller than upper bound")
            if lower < canonical[name]["lower"] or upper > canonical[name]["upper"]:
                raise ValueError(f"{name} bounds exceed the validated physical range")
        return value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "archived"] | None = None
    design_space: dict[str, dict[str, Any]] | None = None

    @field_validator("design_space")
    @classmethod
    def validate_updated_design_space(cls, value):
        if value is None:
            return value
        return ProjectCreate(name="bounds-validation", design_space=value).design_space


class ProjectView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    status: str
    design_space: dict[str, dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class DesignCreate(BaseModel):
    name: str = Field(default="Heat sink design", min_length=1, max_length=160)
    parameters: DesignParameters


class DesignCreateForProject(DesignCreate):
    project_id: str


class DesignView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    version: int
    parameters: dict[str, Any]
    created_at: datetime


class ApiMeta(BaseModel):
    request_id: str
    project_id: str | None = None
    job_id: str | None = None
    model_id: str | None = None
    dataset_version: str | None = None
    status: str = "success"


class ApiEnvelope(BaseModel):
    data: Any
    meta: ApiMeta
    error: dict[str, Any] | None = None
