import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from app.domain.cae import OpenFoamCampaignRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_history import load_campaign_report
from app.services.openfoam_campaign import (
    campaign_id_for_request,
    expected_campaign_case_id,
)
from app.services.openfoam_solve import (
    CHECKPOINT_FILENAME,
    inspect_checkpoint_metadata,
)
from app.services.jobs import JobQueue


SOLVE_RUN_PATTERN = re.compile(r"^solve_[0-9a-f]{12}$")


def _blocked(
    campaign_id: str,
    report: dict[str, Any],
    request: OpenFoamCampaignRequest,
    reason: str,
    detail: str,
    *,
    checkpoint_available: bool = False,
) -> dict[str, Any]:
    return {
        "campaign_id": campaign_id,
        "resume_ready": False,
        "reason": reason,
        "detail": detail,
        "mesh_profile": report.get("mesh_profile"),
        "case_id": report.get("case_id"),
        "current_time_s": report.get("latest_time_s"),
        "requested_target_end_time_s": request.target_end_time_s,
        "resume_from_run_id": report.get("next_resume_run_id"),
        "checkpoint_available": checkpoint_available,
        "resume_payload": None,
    }


def preview_campaign_resume(
    campaign_id: str,
    request: OpenFoamCampaignRequest,
    repository: ArtifactRepository,
) -> dict[str, Any]:
    report = load_campaign_report(repository, campaign_id)
    expected_case_id = expected_campaign_case_id(request, repository)
    if report.get("results_available"):
        return _blocked(
            campaign_id,
            report,
            request,
            "already_converged",
            "The selected campaign already converged; continue with mesh independence instead.",
        )
    if report.get("case_id") != expected_case_id:
        return _blocked(
            campaign_id,
            report,
            request,
            "case_fingerprint_mismatch",
            "The current design, mesh profile, or boundary conditions do not match the checkpoint.",
        )
    if report.get("mesh_profile") != request.mesh_profile:
        return _blocked(
            campaign_id,
            report,
            request,
            "mesh_profile_mismatch",
            "The selected campaign belongs to a different mesh profile.",
        )

    resume_run_id = report.get("next_resume_run_id")
    if not isinstance(resume_run_id, str) or not SOLVE_RUN_PATTERN.fullmatch(
        resume_run_id
    ):
        return _blocked(
            campaign_id,
            report,
            request,
            "resume_id_unavailable",
            "The selected campaign did not publish a valid successor checkpoint ID.",
        )

    try:
        solve_path = repository.cae_artifact_path(
            resume_run_id, "solve-report.json"
        )
        solve_report = json.loads(solve_path.read_text(encoding="utf-8"))
        if not isinstance(solve_report, dict):
            raise ValueError("solve report must be an object")
        checkpoint = repository.cae_artifact_path(
            resume_run_id, CHECKPOINT_FILENAME
        )
        metadata = inspect_checkpoint_metadata(checkpoint, expected_case_id)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
        return _blocked(
            campaign_id,
            report,
            request,
            "checkpoint_unavailable",
            "The immutable checkpoint or its metadata is missing, invalid, or belongs to another case.",
        )

    if solve_report.get("case_id") != expected_case_id:
        return _blocked(
            campaign_id,
            report,
            request,
            "checkpoint_case_mismatch",
            "The solve report does not match the requested case fingerprint.",
        )
    try:
        checkpoint_time = float(metadata.get("latest_time_s"))
        solve_time = float(solve_report.get("latest_time_s"))
    except (TypeError, ValueError):
        return _blocked(
            campaign_id,
            report,
            request,
            "checkpoint_time_invalid",
            "Checkpoint metadata or solve report contains an invalid latest time.",
        )
    if not math.isfinite(checkpoint_time) or not math.isfinite(solve_time):
        return _blocked(
            campaign_id,
            report,
            request,
            "checkpoint_time_invalid",
            "Checkpoint metadata or solve report contains an invalid latest time.",
        )
    if abs(checkpoint_time - solve_time) > 1e-12:
        return _blocked(
            campaign_id,
            report,
            request,
            "checkpoint_time_mismatch",
            "Checkpoint metadata and solve report disagree about the latest time.",
        )
    if request.target_end_time_s <= checkpoint_time + 1e-15:
        return _blocked(
            campaign_id,
            report,
            request,
            "target_time_not_advanced",
            "Increase target end time beyond the selected checkpoint before resuming.",
            checkpoint_available=True,
        )

    return {
        "campaign_id": campaign_id,
        "resume_ready": True,
        "reason": "ready",
        "detail": "Case fingerprint, checkpoint metadata, and target-time advance are valid.",
        "mesh_profile": request.mesh_profile,
        "case_id": expected_case_id,
        "current_time_s": checkpoint_time,
        "requested_target_end_time_s": request.target_end_time_s,
        "resume_from_run_id": resume_run_id,
        "checkpoint_available": True,
        "resume_payload": None,
    }


def _resume_attempt_id(
    campaign_id: str,
    request: OpenFoamCampaignRequest,
    preview: dict[str, Any],
    repository: ArtifactRepository,
) -> str:
    return repository.version(
        {
            "parent_campaign_id": campaign_id,
            "case_id": preview["case_id"],
            "resume_from_run_id": preview["resume_from_run_id"],
            "request": request.model_dump(mode="json"),
        },
        "resume",
    )


def enqueue_campaign_resume(
    campaign_id: str,
    request: OpenFoamCampaignRequest,
    repository: ArtifactRepository,
    queue: JobQueue,
) -> dict[str, Any]:
    if any(
        (
            request.resume_from_run_id,
            request.parent_campaign_id,
            request.resume_attempt_id,
        )
    ):
        raise ValueError("Resume identity is issued only by the atomic resume endpoint")
    preview = preview_campaign_resume(campaign_id, request, repository)
    if not preview["resume_ready"]:
        return preview

    resume_attempt_id = _resume_attempt_id(
        campaign_id, request, preview, repository
    )
    lineage = {
        "resume_attempt_id": resume_attempt_id,
        "parent_campaign_id": campaign_id,
        "case_id": preview["case_id"],
        "checkpoint_run_id": preview["resume_from_run_id"],
        "checkpoint_time_s": preview["current_time_s"],
        "requested_target_end_time_s": preview["requested_target_end_time_s"],
    }
    payload = {
        **request.model_dump(mode="json"),
        "resume_from_run_id": preview["resume_from_run_id"],
        "parent_campaign_id": campaign_id,
        "resume_attempt_id": resume_attempt_id,
    }
    issued_request = OpenFoamCampaignRequest.model_validate(payload)
    successor_campaign_id = campaign_id_for_request(issued_request, repository)
    lineage["successor_campaign_id"] = successor_campaign_id
    try:
        completed_report = load_campaign_report(repository, successor_campaign_id)
    except FileNotFoundError:
        completed_report = None
    if completed_report is not None:
        job = {
            "job_id": f"job_{resume_attempt_id}",
            "task": "cae_campaign",
            "status": "finished",
            "result": completed_report,
            "progress": 100,
            "stage": "completed",
            "queue": "thermoform-cae",
            "cancel_requested": False,
            "lineage": lineage,
            "deduplicated": True,
        }
    else:
        job = queue.enqueue_once(
            "cae_campaign",
            payload,
            resume_attempt_id,
            metadata={"lineage": lineage},
        )
    deduplicated = bool(job.get("deduplicated"))
    dispatch = {
        **lineage,
        "job_id": job["job_id"],
        "queue": job.get("queue", "thermoform-cae"),
        "status_at_dispatch": job["status"],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    repository.save_cae_artifact(
        resume_attempt_id,
        "resume-dispatch.json",
        json.dumps(dispatch, indent=2, sort_keys=True),
    )
    return {
        **preview,
        "reason": "deduplicated" if deduplicated else "queued",
        "detail": (
            "This resume attempt already exists; the existing job or completed campaign was reused."
            if deduplicated
            else "Checkpoint compatibility was validated and the successor campaign was queued in one server operation."
        ),
        "resume_payload": None,
        "resume_attempt_id": resume_attempt_id,
        "lineage": lineage,
        "dispatch": dispatch,
        "deduplicated": deduplicated,
        "job": job,
    }


def validate_issued_resume_request(
    request: OpenFoamCampaignRequest,
    repository: ArtifactRepository,
) -> None:
    if not request.resume_from_run_id:
        return
    if not request.parent_campaign_id or not request.resume_attempt_id:
        raise ValueError("Resume request is missing server-issued lineage")
    base_request = OpenFoamCampaignRequest.model_validate(
        {
            **request.model_dump(mode="json"),
            "resume_from_run_id": None,
            "parent_campaign_id": None,
            "resume_attempt_id": None,
        }
    )
    preview = preview_campaign_resume(
        request.parent_campaign_id, base_request, repository
    )
    expected_attempt_id = _resume_attempt_id(
        request.parent_campaign_id, base_request, preview, repository
    )
    if (
        not preview["resume_ready"]
        or preview["resume_from_run_id"] != request.resume_from_run_id
        or expected_attempt_id != request.resume_attempt_id
    ):
        raise ValueError("Resume lineage no longer matches the immutable checkpoint")
