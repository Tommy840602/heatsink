import json
import re
from pathlib import Path
from typing import Any

from app.repositories.artifacts import ArtifactRepository


CAMPAIGN_PATTERN = re.compile(r"^campaign_[0-9a-f]{12}$")
MESH_STUDY_PATTERN = re.compile(r"^meshstudy_[0-9a-f]{12}$")


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
