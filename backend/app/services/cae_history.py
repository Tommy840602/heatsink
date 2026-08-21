import json
import re
from pathlib import Path
from typing import Any

from app.repositories.artifacts import ArtifactRepository


CAMPAIGN_PATTERN = re.compile(r"^campaign_[0-9a-f]{12}$")
MESH_STUDY_PATTERN = re.compile(r"^meshstudy_[0-9a-f]{12}$")
RESUME_ATTEMPT_PATTERN = re.compile(r"^resume_[0-9a-f]{12}$")
WATCHDOG_PATTERN = re.compile(r"^watchdog_[0-9a-f]{12}$")
RESUME_EVENT_ORDER = {
    "queued": 0,
    "started": 1,
    "failed": 2,
    "completed": 2,
    "cancelled": 2,
}


def _read_report(path: Path) -> dict[str, Any] | None:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return report if isinstance(report, dict) else None


def _newest_first(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        reports,
        key=lambda report: str(report.get("generated_at") or ""),
        reverse=True,
    )


def _campaign_summary(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "campaign_id",
        "case_id",
        "mesh_profile",
        "study_fingerprint",
        "status",
        "stop_reason",
        "segments_completed",
        "latest_time_s",
        "target_end_time_s",
        "results_available",
        "numerically_converged",
        "mesh_independence_validated",
        "design_result_available",
        "next_resume_run_id",
        "generated_at",
        "downloads",
    )
    return {key: report.get(key) for key in keys}


def _mesh_study_summary(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "mesh_study_id",
        "status",
        "campaign_ids",
        "study_fingerprint",
        "campaigns_validated",
        "validation_errors",
        "comparisons",
        "limits",
        "gates",
        "mesh_independence_validated",
        "results_available",
        "design_result_available",
        "recommended_profile",
        "generated_at",
        "downloads",
        "notice",
    )
    return {key: report.get(key) for key in keys}


def _resume_dispatch_summary(
    report: dict[str, Any], repository: ArtifactRepository
) -> dict[str, Any]:
    attempt_id = str(report.get("resume_attempt_id") or "")
    events = list_resume_events(repository, attempt_id)
    successor_id = str(report.get("successor_campaign_id") or "")
    try:
        successor = load_campaign_report(repository, successor_id)
    except FileNotFoundError:
        successor = None
    latest_event_status = events[-1].get("status") if events else None
    status = (
        successor.get("status")
        if successor
        else latest_event_status or report.get("status_at_dispatch")
    )
    return {
        **report,
        "status": status,
        "stop_reason": successor.get("stop_reason") if successor else None,
        "results_available": bool(successor and successor.get("results_available")),
        "successor_available": successor is not None,
        "events": events,
        "retry_allowed": latest_event_status == "failed"
        and isinstance(report.get("request"), dict),
    }


def load_resume_dispatch(
    repository: ArtifactRepository, resume_attempt_id: str
) -> dict[str, Any]:
    if not RESUME_ATTEMPT_PATTERN.fullmatch(resume_attempt_id):
        raise FileNotFoundError(resume_attempt_id)
    path = repository.cae_artifact_path(
        resume_attempt_id, "resume-dispatch.json"
    )
    report = _read_report(path)
    if report is None or report.get("resume_attempt_id") != resume_attempt_id:
        raise FileNotFoundError(resume_attempt_id)
    return report


def list_resume_events(
    repository: ArtifactRepository, resume_attempt_id: str
) -> list[dict[str, Any]]:
    if not RESUME_ATTEMPT_PATTERN.fullmatch(resume_attempt_id):
        return []
    events = [
        event
        for path in repository.list_cae_artifact_paths(
            resume_attempt_id, "resume-event-"
        )
        if (event := _read_report(path)) is not None
        and event.get("resume_attempt_id") == resume_attempt_id
        and event.get("status") in RESUME_EVENT_ORDER
    ]
    return sorted(
        events,
        key=lambda event: (
            RESUME_EVENT_ORDER[str(event["status"])],
            str(event.get("generated_at") or ""),
        ),
    )


def list_campaign_reports(
    repository: ArtifactRepository, limit: int = 50
) -> list[dict[str, Any]]:
    reports = [
        report
        for path in repository.list_cae_report_paths(
            "campaign-report.json", "campaign_"
        )
        if (report := _read_report(path)) is not None
        and CAMPAIGN_PATTERN.fullmatch(str(report.get("campaign_id") or ""))
    ]
    return [_campaign_summary(report) for report in _newest_first(reports)[:limit]]


def load_campaign_report(
    repository: ArtifactRepository, campaign_id: str
) -> dict[str, Any]:
    if not CAMPAIGN_PATTERN.fullmatch(campaign_id):
        raise FileNotFoundError(campaign_id)
    path = repository.cae_artifact_path(campaign_id, "campaign-report.json")
    report = _read_report(path)
    if report is None or report.get("campaign_id") != campaign_id:
        raise FileNotFoundError(campaign_id)
    return report


def list_mesh_study_reports(
    repository: ArtifactRepository, limit: int = 20
) -> list[dict[str, Any]]:
    reports = [
        report
        for path in repository.list_cae_report_paths(
            "mesh-study-report.json", "meshstudy_"
        )
        if (report := _read_report(path)) is not None
        and MESH_STUDY_PATTERN.fullmatch(str(report.get("mesh_study_id") or ""))
    ]
    return [
        _mesh_study_summary(report) for report in _newest_first(reports)[:limit]
    ]


def load_mesh_study_report(
    repository: ArtifactRepository, mesh_study_id: str
) -> dict[str, Any]:
    if not MESH_STUDY_PATTERN.fullmatch(mesh_study_id):
        raise FileNotFoundError(mesh_study_id)
    path = repository.cae_artifact_path(mesh_study_id, "mesh-study-report.json")
    report = _read_report(path)
    if report is None or report.get("mesh_study_id") != mesh_study_id:
        raise FileNotFoundError(mesh_study_id)
    return report


def list_resume_dispatches(
    repository: ArtifactRepository, limit: int = 50
) -> list[dict[str, Any]]:
    reports = [
        report
        for path in repository.list_cae_report_paths(
            "resume-dispatch.json", "resume_"
        )
        if (report := _read_report(path)) is not None
        and RESUME_ATTEMPT_PATTERN.fullmatch(
            str(report.get("resume_attempt_id") or "")
        )
    ]
    return [
        _resume_dispatch_summary(report, repository)
        for report in _newest_first(reports)[:limit]
    ]


def list_resume_watchdog_reports(
    repository: ArtifactRepository, limit: int = 20
) -> list[dict[str, Any]]:
    reports = [
        report
        for path in repository.list_cae_report_paths(
            "resume-watchdog-report.json", "watchdog_"
        )
        if (report := _read_report(path)) is not None
        and WATCHDOG_PATTERN.fullmatch(str(report.get("watchdog_id") or ""))
    ]
    return _newest_first(reports)[:limit]


def load_latest_resume_watchdog(
    repository: ArtifactRepository,
) -> dict[str, Any] | None:
    reports = list_resume_watchdog_reports(repository, 1)
    return reports[0] if reports else None
