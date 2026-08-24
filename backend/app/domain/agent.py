from typing import Any, Literal

from pydantic import BaseModel, Field


class EngineeringAgentRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=4000)
    project_id: str | None = None
    dataset_version: str | None = None
    model_id: str | None = None
    seed: int = Field(default=42, ge=0)
    allowed_tools: list[
        Literal[
            "run_doe",
            "run_simulation",
            "train_surrogate",
            "evaluate_models",
            "optimize_design",
            "generate_cad",
            "compare_designs",
        ]
    ] = Field(
        default_factory=lambda: [
            "run_doe",
            "run_simulation",
            "train_surrogate",
            "evaluate_models",
            "optimize_design",
            "generate_cad",
            "compare_designs",
        ]
    )
    context: dict[str, Any] = Field(default_factory=dict)


class EngineeringAgentResponse(BaseModel):
    agent_run_id: str
    status: Literal["completed"] = "completed"
    instruction: str
    plan: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    recommendation: dict[str, Any]
    traceability: dict[str, Any]
