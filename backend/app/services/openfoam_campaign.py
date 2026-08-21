import json
import time
from datetime import UTC, datetime
from typing import Any, Callable

from app.domain.cae import OpenFoamCampaignRequest, OpenFoamSolveRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam import OPENFOAM_TEMPLATE_VERSION
from app.services.openfoam_solve import run_openfoam_solve


CAMPAIGN_CONTRACT_VERSION = "cht-campaign-v2"
ProgressCallback = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]
SolveRunner = Callable[[OpenFoamSolveRequest, ArtifactRepository], dict[str, Any]]


def expected_campaign_case_id(
    request: OpenFoamCampaignRequest, repository: ArtifactRepository
) -> str:
    return repository.version(
        {
            "design": request.design.model_dump(),
            "mesh_profile": request.mesh_profile,
            "heat_load_w": request.heat_load_w,
            "ambient_temperature_c": request.ambient_temperature_c,
            "solver": "chtMultiRegionFoam",
            "template": OPENFOAM_TEMPLATE_VERSION,
        },
        "cae",
    )


def _expected_case_id(
    request: OpenFoamCampaignRequest, repository: ArtifactRepository
) -> str:
    return expected_campaign_case_id(request, repository)


def campaign_id_for_request(
    request: OpenFoamCampaignRequest, repository: ArtifactRepository
) -> str:
    request_payload = request.model_dump(mode="json")
    if request.retry_of_attempt_id is None:
        request_payload.pop("retry_of_attempt_id", None)
    if request.root_resume_attempt_id is None:
        request_payload.pop("root_resume_attempt_id", None)
    if request.retry_index == 0:
        request_payload.pop("retry_index", None)
    return repository.version(
        {
            "case_id": expected_campaign_case_id(request, repository),
            "request": request_payload,
            "contract": CAMPAIGN_CONTRACT_VERSION,
        },
        "campaign",
    )


def _load_solve_report(
    repository: ArtifactRepository, run_id: str
) -> dict[str, Any]:
    report = repository.cae_artifact_path(run_id, "solve-report.json")
    return json.loads(report.read_text(encoding="utf-8"))


def _segment_snapshot(index: int, result: dict[str, Any]) -> dict[str, Any]:
    readiness = result.get("response_readiness", {})
    return {
        "index": index,
        "solve_run_id": result.get("solve_run_id"),
        "resumed_from_run_id": result.get("resumed_from_run_id"),
        "status": result.get("status"),
        "execution_status": result.get("execution_status"),
        "latest_time_s": result.get("latest_time_s"),
        "target_end_time_s": result.get("target_end_time_s"),
        "checkpoint_created": bool(result.get("checkpoint_created")),
        "results_available": bool(result.get("results_available")),
        "response_sample_count": readiness.get("response_sample_count", 0),
        "gates": readiness.get("gates", {}),
    }


def run_openfoam_campaign(
    request: OpenFoamCampaignRequest,
    repository: ArtifactRepository | None = None,
    *,
    solve_runner: SolveRunner = run_openfoam_solve,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    progress_callback = progress_callback or (lambda _current, _total, _stage: None)
    should_cancel = should_cancel or (lambda: False)
    expected_case_id = expected_campaign_case_id(request, repository)
    campaign_id = campaign_id_for_request(request, repository)
    report_name = "campaign-report.json"
    try:
        existing = repository.cae_artifact_path(campaign_id, report_name)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        return json.loads(existing.read_text(encoding="utf-8"))

    started = time.monotonic()
    segments: list[dict[str, Any]] = []
    resume_run_id = request.resume_from_run_id
    resume_checkpoint_time_s: float | None = None
    current_time_s = 0.0
    last_result: dict[str, Any] | None = None
    stop_reason = "segment_limit"

    if resume_run_id:
        try:
            last_result = _load_solve_report(repository, resume_run_id)
        except (FileNotFoundError, json.JSONDecodeError):
            stop_reason = "resume_unavailable"
        else:
            if last_result.get("case_id") != expected_case_id:
                stop_reason = "resume_case_mismatch"
            else:
                current_time_s = float(last_result.get("latest_time_s") or 0.0)
                resume_checkpoint_time_s = current_time_s
                if last_result.get("results_available"):
                    stop_reason = "converged"

    can_run = stop_reason not in {
        "resume_unavailable",
        "resume_case_mismatch",
        "converged",
    }
    while can_run:
        if should_cancel():
            stop_reason = "cancelled"
            break
        if current_time_s >= request.target_end_time_s:
            stop_reason = "target_time_reached"
            break
        if len(segments) >= request.max_segments:
            stop_reason = "segment_limit"
            break
        remaining_runtime = request.max_total_runtime_seconds - (
            time.monotonic() - started
        )
        if remaining_runtime < 30:
            stop_reason = "runtime_budget"
            break

        index = len(segments) + 1
        segment_target = min(
            request.target_end_time_s,
            current_time_s + request.segment_duration_s,
        )
        progress_callback(index, request.max_segments, "running_cae_segment")
        solve_request = OpenFoamSolveRequest(
            design=request.design,
            mesh_profile=request.mesh_profile,
            heat_load_w=request.heat_load_w,
            ambient_temperature_c=request.ambient_temperature_c,
            target_end_time_s=segment_target,
            delta_t_s=request.delta_t_s,
            write_interval_steps=request.write_interval_steps,
            parallel_processes=request.parallel_processes,
            max_runtime_seconds=max(
                30,
                min(request.segment_runtime_seconds, int(remaining_runtime)),
            ),
            resume_from_run_id=resume_run_id,
            criteria=request.criteria,
        )
        result = solve_runner(solve_request, repository)
        last_result = result
        segments.append(_segment_snapshot(index, result))

        if result.get("case_id") != expected_case_id:
            stop_reason = "segment_case_mismatch"
            break
        if result.get("results_available"):
            stop_reason = "converged"
            break
        if not result.get("checkpoint_created") or not result.get("solve_run_id"):
            stop_reason = "checkpoint_unavailable"
            break
        latest_time = result.get("latest_time_s")
        if latest_time is None or float(latest_time) <= current_time_s + 1e-15:
            stop_reason = "no_time_progress"
            break
        if result.get("execution_status") not in {
            "completed",
            "target_already_reached",
            "timed_out",
        }:
            stop_reason = "segment_failed"
            break
        current_time_s = float(latest_time)
        resume_run_id = str(result["solve_run_id"])
        progress_callback(index, request.max_segments, "checkpoint_saved")

    results_available = bool(
        last_result and last_result.get("results_available") and stop_reason == "converged"
    )
    failure_reasons = {
        "resume_unavailable",
        "resume_case_mismatch",
        "segment_case_mismatch",
        "checkpoint_unavailable",
        "no_time_progress",
        "segment_failed",
    }
    status = (
        "passed"
        if results_available
        else "cancelled"
        if stop_reason == "cancelled"
        else "failed"
        if stop_reason in failure_reasons
        else "completed_unconverged"
    )
    result = {
        "campaign_id": campaign_id,
        "case_id": expected_case_id,
        "mesh_profile": request.mesh_profile,
        "study_fingerprint": repository.version(
            {
                "design": request.design.model_dump(),
                "heat_load_w": request.heat_load_w,
                "ambient_temperature_c": request.ambient_temperature_c,
                "solver": "chtMultiRegionFoam",
                "template": OPENFOAM_TEMPLATE_VERSION,
            },
            "mesh-study",
        ),
        "contract_version": CAMPAIGN_CONTRACT_VERSION,
        "status": status,
        "stop_reason": stop_reason,
        "segments_completed": len(segments),
        "segments": segments,
        "latest_time_s": current_time_s,
        "target_end_time_s": request.target_end_time_s,
        "runtime_seconds": time.monotonic() - started,
        "results_available": results_available,
        "numerically_converged": results_available,
        "mesh_independence_validated": False,
        "design_result_available": False,
        "not_cfd_result": not results_available,
        "responses": last_result.get("responses") if last_result else None,
        "response_readiness": (
            last_result.get("response_readiness") if last_result else None
        ),
        "resume_from_run_id": request.resume_from_run_id,
        "lineage": (
            {
                "resume_attempt_id": request.resume_attempt_id,
                "parent_campaign_id": request.parent_campaign_id,
                "case_id": expected_case_id,
                "checkpoint_run_id": request.resume_from_run_id,
                "checkpoint_time_s": resume_checkpoint_time_s,
                "requested_target_end_time_s": request.target_end_time_s,
                **(
                    {
                        "retry_of_attempt_id": request.retry_of_attempt_id,
                        "root_resume_attempt_id": request.root_resume_attempt_id,
                        "retry_index": request.retry_index,
                    }
                    if request.retry_of_attempt_id
                    else {}
                ),
            }
            if request.resume_from_run_id
            else None
        ),
        "next_resume_run_id": (
            last_result.get("solve_run_id")
            if last_result and last_result.get("checkpoint_created")
            else None
        ),
        "generated_at": datetime.now(UTC).isoformat(),
        "downloads": {
            "report": f"/api/v1/cae/{campaign_id}/artifacts/{report_name}",
            "latest_checkpoint": (
                last_result.get("downloads", {}).get("checkpoint")
                if last_result
                else None
            ),
        },
        "notice": (
            "The campaign converged numerically; a coarse/medium/fine mesh-independence study is still required for a publishable design result."
            if results_available
            else "The campaign stopped safely without publishing unconverged values as CFD results."
        ),
    }
    repository.save_cae_artifact(
        campaign_id, report_name, json.dumps(result, indent=2, sort_keys=True)
    )
    return result
