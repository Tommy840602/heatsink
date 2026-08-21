import json
from datetime import UTC, datetime
from typing import Any

from app.domain.cae import OpenFoamMeshIndependenceRequest
from app.repositories.artifacts import ArtifactRepository


MESH_STUDY_CONTRACT_VERSION = "mesh-independence-v1"
PROFILES = ("coarse", "medium", "fine")


def _relative_change_percent(reference: float, candidate: float) -> float:
    return abs(candidate - reference) / max(abs(candidate), 1e-12) * 100


def evaluate_mesh_independence(
    request: OpenFoamMeshIndependenceRequest,
    repository: ArtifactRepository | None = None,
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    study_id = repository.version(
        {
            "campaign_ids": request.campaign_ids,
            "t_max_limit": request.max_t_max_relative_change_percent,
            "pressure_drop_limit": request.max_pressure_drop_relative_change_percent,
            "contract": MESH_STUDY_CONTRACT_VERSION,
        },
        "meshstudy",
    )
    report_name = "mesh-study-report.json"
    try:
        existing = repository.cae_artifact_path(study_id, report_name)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        return json.loads(existing.read_text(encoding="utf-8"))

    campaigns: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for profile in PROFILES:
        campaign_id = request.campaign_ids[profile]
        try:
            path = repository.cae_artifact_path(campaign_id, "campaign-report.json")
            report = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            errors.append(f"{profile} campaign report is unavailable or invalid")
            continue
        campaigns[profile] = report
        if report.get("mesh_profile") != profile:
            errors.append(f"{profile} campaign mesh profile does not match")
        if not report.get("results_available"):
            errors.append(f"{profile} campaign has no numerically converged responses")
        responses = report.get("responses") or {}
        if responses.get("t_max_c") is None or responses.get("pressure_drop_pa") is None:
            errors.append(f"{profile} campaign is missing required responses")

    fingerprints = {
        report.get("study_fingerprint")
        for report in campaigns.values()
        if report.get("study_fingerprint")
    }
    if len(fingerprints) != 1 or len(campaigns) != len(PROFILES):
        errors.append("campaigns do not share one design and boundary-condition fingerprint")

    comparisons: dict[str, Any] = {}
    if not errors:
        for lower, upper in (("coarse", "medium"), ("medium", "fine")):
            lower_response = campaigns[lower]["responses"]
            upper_response = campaigns[upper]["responses"]
            comparisons[f"{lower}_to_{upper}"] = {
                "t_max_relative_change_percent": _relative_change_percent(
                    float(lower_response["t_max_c"]),
                    float(upper_response["t_max_c"]),
                ),
                "pressure_drop_relative_change_percent": _relative_change_percent(
                    float(lower_response["pressure_drop_pa"]),
                    float(upper_response["pressure_drop_pa"]),
                ),
            }

    decisive = comparisons.get("medium_to_fine", {})
    t_max_passed = bool(
        decisive
        and decisive["t_max_relative_change_percent"]
        <= request.max_t_max_relative_change_percent
    )
    pressure_drop_passed = bool(
        decisive
        and decisive["pressure_drop_relative_change_percent"]
        <= request.max_pressure_drop_relative_change_percent
    )
    mesh_independent = bool(not errors and t_max_passed and pressure_drop_passed)
    fine = campaigns.get("fine")
    result = {
        "mesh_study_id": study_id,
        "contract_version": MESH_STUDY_CONTRACT_VERSION,
        "status": "passed" if mesh_independent else "failed",
        "campaign_ids": request.campaign_ids,
        "study_fingerprint": next(iter(fingerprints), None),
        "campaigns_validated": not errors,
        "validation_errors": errors,
        "comparisons": comparisons,
        "limits": {
            "max_t_max_relative_change_percent": request.max_t_max_relative_change_percent,
            "max_pressure_drop_relative_change_percent": request.max_pressure_drop_relative_change_percent,
        },
        "gates": {
            "all_campaigns_converged": not errors,
            "t_max_mesh_independent": t_max_passed,
            "pressure_drop_mesh_independent": pressure_drop_passed,
        },
        "mesh_independence_validated": mesh_independent,
        "results_available": mesh_independent,
        "design_result_available": mesh_independent,
        "not_cfd_result": not mesh_independent,
        "recommended_profile": "fine" if mesh_independent else None,
        "responses": fine.get("responses") if fine and mesh_independent else None,
        "generated_at": datetime.now(UTC).isoformat(),
        "downloads": {
            "report": f"/api/v1/cae/{study_id}/artifacts/{report_name}"
        },
        "notice": (
            "The numerically converged coarse, medium, and fine campaigns passed the configured mesh-independence limits."
            if mesh_independent
            else "No publishable design result exists until all three campaigns converge and the medium-to-fine response changes pass."
        ),
    }
    repository.save_cae_artifact(
        study_id, report_name, json.dumps(result, indent=2, sort_keys=True)
    )
    return result
