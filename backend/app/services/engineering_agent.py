from datetime import UTC, datetime
import re
from typing import Any

from app.domain.agent import EngineeringAgentRequest
from app.domain.models import DoeRequest
from app.domain.phase1 import OptimizationRequest, Phase1WorkflowRequest
from app.domain.phase2 import CadGenerationRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.cad import generate_cad
from app.services.doe import generate_doe
from app.services.optimization import optimize
from app.services.surrogates import train_surrogates
from app.services.workflow import run_phase1


def _method(instruction: str) -> str:
    normalized = instruction.lower()
    if "fractional" in normalized or "部分因子" in instruction:
        return "Fractional Factorial"
    if "full factorial" in normalized or "全因子" in instruction:
        return "Full Factorial"
    if "ccd" in normalized or "central composite" in normalized:
        return "CCD"
    if "bbd" in normalized or "box-behnken" in normalized:
        return "BBD"
    return "LHS"


def _wants_cad(instruction: str) -> bool:
    normalized = instruction.lower()
    return any(token in normalized for token in ("cad", "step", "stl", "geometry", "幾何", "圖檔"))


def _numeric_constraint(instruction: str, label: str, default: float | None) -> float | None:
    match = re.search(rf"{label}\s*(?:<|≤|低於|小於)\s*(\d+(?:\.\d+)?)", instruction, re.IGNORECASE)
    return float(match.group(1)) if match else default


def execute_engineering_agent(
    request: EngineeringAgentRequest,
    repository: ArtifactRepository | None = None,
) -> dict[str, Any]:
    """Execute a bounded, auditable engineering tool plan without arbitrary code execution."""
    repository = repository or ArtifactRepository()
    plan: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    dataset_version = request.dataset_version
    model_id = request.model_id
    recommendation: dict[str, Any] = {}
    t_max_limit = float(
        request.context.get(
            "t_max_limit", _numeric_constraint(request.instruction, r"T\s*max", 80.0)
        )
    )
    parsed_mass_limit = _numeric_constraint(request.instruction, "Mass", None)
    mass_limit = request.context.get("mass_limit", parsed_mass_limit)
    mass_limit = float(mass_limit) if mass_limit is not None else None
    pressure_drop_limit = float(
        request.context.get(
            "pressure_drop_limit",
            _numeric_constraint(request.instruction, r"(?:Δ\s*P|pressure\s*drop)", 35.0),
        )
    )

    if dataset_version is None and model_id is None:
        required = {
            "run_doe",
            "run_simulation",
            "train_surrogate",
            "evaluate_models",
            "optimize_design",
        }
        missing = sorted(required.difference(request.allowed_tools))
        if missing:
            raise ValueError(
                f"Missing required agent tool permissions: {', '.join(missing)}"
            )
        method = _method(request.instruction)
        plan.append({"tool": "run_doe", "reason": "No dataset supplied; create the initial engineering evidence."})
        plan.append({"tool": "run_simulation", "reason": "Generate reduced-order physics responses; these are explicitly not CFD."})
        plan.append({"tool": "train_surrogate", "reason": "Fit RSM, RF, XGBoost, and GPR candidates."})
        plan.append({"tool": "evaluate_models", "reason": "Select by cross-validated RMSE, not training R²."})
        plan.append({"tool": "optimize_design", "reason": "Search the constrained Pareto design space."})
        if "compare_designs" in request.allowed_tools:
            plan.append({"tool": "compare_designs", "reason": "Expose Pareto trade-offs and the balanced recommendation."})
        workflow = run_phase1(
            Phase1WorkflowRequest(
                project_id=request.project_id,
                method=method,
                runs=int(request.context.get("runs", 48)),
                seed=request.seed,
                noise_std=float(request.context.get("noise_std", 0.0)),
                optimization_generations=int(request.context.get("generations", 20)),
                t_max_limit=t_max_limit,
                pressure_drop_limit=pressure_drop_limit,
                mass_limit=mass_limit,
            ),
            repository,
        )
        dataset_version = workflow["dataset_version"]
        model_id = workflow["model_id"]
        recommendation = workflow["optimization"]["recommended"] or {}
        tool_results.append(
            {
                "tool": "run_doe",
                "workflow_id": workflow["workflow_id"],
                "dataset_version": dataset_version,
                "model_id": model_id,
                "experiment_count": workflow["experiment_count"],
            }
        )
        tool_results.extend(
            [
                {"tool": "run_simulation", "dataset_version": dataset_version, "result_kind": "physics_model", "not_cfd_result": True},
                {"tool": "train_surrogate", "model_id": model_id},
                {"tool": "evaluate_models", "selected_models": workflow["selected_models"], "metrics": workflow["model_metrics"]},
                {"tool": "optimize_design", "recommended": recommendation, "pareto_count": len(workflow["optimization"].get("pareto", []))},
            ]
        )
        if "compare_designs" in request.allowed_tools:
            tool_results.append(
                {
                    "tool": "compare_designs",
                    "candidates": workflow["optimization"].get("pareto", []),
                    "recommended": recommendation,
                }
            )
    elif model_id is None:
        if not {"train_surrogate", "evaluate_models"}.issubset(request.allowed_tools):
            raise ValueError("train_surrogate and evaluate_models permissions are required when no model is supplied")
        plan.append({"tool": "train_surrogate", "reason": "A dataset exists but no surrogate model was supplied."})
        plan.append({"tool": "evaluate_models", "reason": "Compare generalization performance with cross-validation."})
        records = repository.load_dataset(dataset_version)
        model_id, metrics, selected = train_surrogates(records, request.seed, repository)
        tool_results.append(
            {
                "tool": "train_surrogate",
                "model_id": model_id,
                "selected_models": selected,
                "metrics": metrics,
            }
        )
        tool_results.append({"tool": "evaluate_models", "model_id": model_id, "selected_models": selected, "metrics": metrics})

    if not recommendation:
        if "optimize_design" not in request.allowed_tools:
            raise ValueError("optimize_design permission is required to produce a recommendation")
        plan.append({"tool": "optimize_design", "reason": "Find a constrained Pareto recommendation from the surrogate."})
        optimization = optimize(
            OptimizationRequest(
                model_id=model_id,
                mode="multi",
                objectives=request.context.get(
                    "objectives", ["t_max", "pressure_drop", "mass"]
                ),
                t_max_limit=t_max_limit,
                pressure_drop_limit=pressure_drop_limit,
                mass_limit=mass_limit,
                seed=request.seed,
                generations=int(request.context.get("generations", 20)),
            ),
            repository,
        )
        recommendation = optimization["recommended"] or {}
        tool_results.append(
            {
                "tool": "optimize_design",
                "model_id": model_id,
                "recommended": recommendation,
                "pareto_count": len(optimization.get("pareto", [])),
            }
        )
        if "compare_designs" in request.allowed_tools:
            plan.append({"tool": "compare_designs", "reason": "Expose Pareto trade-offs and the balanced recommendation."})
            tool_results.append(
                {
                    "tool": "compare_designs",
                    "candidates": optimization.get("pareto", []),
                    "recommended": recommendation,
                }
            )

    if _wants_cad(request.instruction) and recommendation.get("design"):
        if "generate_cad" not in request.allowed_tools:
            raise ValueError("generate_cad permission is required by the instruction")
        from app.domain.models import DesignParameters

        plan.append({"tool": "generate_cad", "reason": "The instruction requests a traceable geometry artifact."})
        cad = generate_cad(
            CadGenerationRequest(design=DesignParameters(**recommendation["design"])),
            repository,
        )
        tool_results.append(
            {
                "tool": "generate_cad",
                "cad_id": cad["cad_id"],
                "step_generated": cad["step_generated"],
                "downloads": cad["downloads"],
            }
        )
        recommendation = {**recommendation, "cad": cad}

    fingerprint = {
        "instruction": request.instruction,
        "project_id": request.project_id,
        "dataset_version": dataset_version,
        "model_id": model_id,
        "seed": request.seed,
        "allowed_tools": request.allowed_tools,
        "interpreted_constraints": {
            "t_max_limit": t_max_limit,
            "pressure_drop_limit": pressure_drop_limit,
            "mass_limit": mass_limit,
        },
        "plan": plan,
    }
    agent_run_id = repository.version(fingerprint, "agent")
    result = {
        "agent_run_id": agent_run_id,
        "status": "completed",
        "instruction": request.instruction,
        "plan": plan,
        "tool_results": tool_results,
        "recommendation": recommendation,
        "traceability": {
            **fingerprint,
            "completed_at": datetime.now(UTC).isoformat(),
            "planner": "deterministic-open-engineering-agent-v1",
            "arbitrary_code_execution": False,
        },
    }
    repository.save_agent_run(agent_run_id, result)
    return result
