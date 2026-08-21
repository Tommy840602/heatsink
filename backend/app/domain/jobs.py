from typing import Any, Literal

from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    task: Literal[
        "phase1",
        "phase2",
        "cae",
        "cae_mesh",
        "cae_smoke",
        "cae_solve",
        "cae_campaign",
        "cae_mesh_study",
        "cae_benchmark",
    ]
    payload: dict[str, Any] = Field(default_factory=dict)


class JobSnapshot(BaseModel):
    job_id: str
    task: str
    status: Literal["queued", "started", "finished", "failed", "deferred", "scheduled", "stopped", "canceled"]
    created_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    stage: str = "queued"
    queue: str = "thermoform"
    cancel_requested: bool = False
    lineage: dict[str, Any] | None = None
    deduplicated: bool = False
