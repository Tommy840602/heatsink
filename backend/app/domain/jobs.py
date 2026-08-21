from typing import Any, Literal

from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    task: Literal["phase1", "phase2", "cae"]
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
