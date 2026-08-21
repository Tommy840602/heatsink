import json
import os
from datetime import UTC, datetime
from typing import Any

from rq.exceptions import NoSuchJobError

from app.repositories.artifacts import ArtifactRepository
from app.services.cae_heartbeat import load_resume_heartbeat
from app.services.cae_history import list_resume_dispatches, list_resume_events
from app.services.cae_resume import record_resume_event
from app.services.jobs import JobQueue, RqJobQueue


TERMINAL_EVENT_STATUSES = {"failed", "completed", "cancelled"}
ACTIVE_JOB_STATUSES = {"queued", "deferred", "scheduled", "started"}
ORPHAN_RUNTIME_BUFFER_SECONDS = 300
WATCHDOG_REPORT_FILENAME = "resume-watchdog-report.json"


def _age_seconds(value: Any, now: datetime) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return max(0.0, (now - timestamp.astimezone(UTC)).total_seconds())


def _terminal_event_for_job(job: dict[str, Any]) -> tuple[str, str] | None:
    status = str(job.get("status") or "")
    if status == "finished":
        result = job.get("result")
        if isinstance(result, dict) and result.get("status") == "cancelled":
            return "cancelled", "rq_finished_cancelled"
        return "completed", "rq_finished"
    if status in {"failed", "stopped"}:
        return "failed", f"rq_{status}"
    if status in {"canceled", "cancelled"}:
        return "cancelled", "rq_cancelled"
    return None


def _terminal_event_for_successor(
    dispatch: dict[str, Any],
) -> tuple[str, str] | None:
    if not dispatch.get("successor_available"):
        return None
    status = str(dispatch.get("status") or "")
    if status == "cancelled":
        return "cancelled", "successor_report_cancelled"
    if status == "failed":
        return "failed", "successor_report_failed"
    return "completed", "successor_report_available"


def _terminal_event_for_heartbeat(
    heartbeat: dict[str, Any] | None,
) -> tuple[str, str] | None:
    if not heartbeat or heartbeat.get("active") is not False:
        return None
    stage = str(heartbeat.get("stage") or "")
    if stage == "failed":
        return "failed", "heartbeat_terminal_failed"
    if stage == "cancelled":
        return "cancelled", "heartbeat_terminal_cancelled"
    if stage == "completed":
        return "completed", "heartbeat_terminal_completed"
    return None


def _heartbeat_grace_seconds(
    heartbeat: dict[str, Any], configured_seconds: int
) -> int:
    try:
        interval = max(1, int(heartbeat.get("heartbeat_interval_seconds", 30)))
    except (TypeError, ValueError):
        interval = 30
    return max(configured_seconds, interval * 3)


def _effective_grace_seconds(
    dispatch: dict[str, Any], configured_seconds: int
) -> int:
    request = dispatch.get("request")
    if not isinstance(request, dict):
        return configured_seconds
    try:
        max_runtime = max(0, int(request.get("max_total_runtime_seconds", 18000)))
        segment_runtime = max(0, int(request.get("segment_runtime_seconds", 3600)))
    except (TypeError, ValueError):
        return configured_seconds
    return max(
        configured_seconds,
        max_runtime + segment_runtime + ORPHAN_RUNTIME_BUFFER_SECONDS,
    )


def reconcile_resume_attempts(
    repository: ArtifactRepository,
    queue: JobQueue,
    *,
    limit: int = 50,
    stale_after_seconds: int = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    attempts: list[dict[str, Any]] = []
    reconciled = 0
    active = 0
    pending_grace = 0

    for dispatch in list_resume_dispatches(repository, limit):
        attempt_id = str(dispatch["resume_attempt_id"])
        events = list_resume_events(repository, attempt_id)
        latest_event = events[-1] if events else None
        latest_status = (
            str(latest_event.get("status"))
            if latest_event
            else str(dispatch.get("status_at_dispatch") or "")
        )
        if latest_status in TERMINAL_EVENT_STATUSES:
            continue

        job_id = str(dispatch.get("job_id") or "")
        successor_terminal = _terminal_event_for_successor(dispatch)
        if successor_terminal is not None:
            event_status, reason = successor_terminal
            event = record_resume_event(
                repository,
                attempt_id,
                event_status,
                stage="job_reconciliation",
                reason=reason,
                job_id=job_id,
                successor_campaign_id=dispatch.get("successor_campaign_id"),
                stop_reason=dispatch.get("stop_reason"),
                results_available=bool(dispatch.get("results_available")),
            )
            reconciled += 1
            attempts.append(
                {
                    "resume_attempt_id": attempt_id,
                    "job_id": job_id,
                    "action": event_status,
                    "reason": reason,
                    "event": event,
                }
            )
            continue

        try:
            job = queue.get(job_id)
        except NoSuchJobError:
            heartbeat = load_resume_heartbeat(repository, attempt_id)
            heartbeat_terminal = _terminal_event_for_heartbeat(heartbeat)
            if heartbeat_terminal is not None:
                event_status, reason = heartbeat_terminal
                event = record_resume_event(
                    repository,
                    attempt_id,
                    event_status,
                    stage="job_reconciliation",
                    reason=reason,
                    job_id=job_id,
                    heartbeat_at=heartbeat.get("heartbeat_at"),
                    heartbeat_stage=heartbeat.get("stage"),
                    successor_campaign_id=dispatch.get("successor_campaign_id"),
                )
                reconciled += 1
                attempts.append(
                    {
                        "resume_attempt_id": attempt_id,
                        "job_id": job_id,
                        "action": event_status,
                        "reason": reason,
                        "event": event,
                    }
                )
                continue
            timestamp = (
                heartbeat.get("heartbeat_at")
                if heartbeat
                else latest_event.get("generated_at")
                if latest_event
                else dispatch.get("generated_at")
            )
            age_seconds = _age_seconds(timestamp, checked_at)
            effective_grace = (
                _heartbeat_grace_seconds(heartbeat, stale_after_seconds)
                if heartbeat
                else _effective_grace_seconds(dispatch, stale_after_seconds)
            )
            if age_seconds is None or age_seconds < effective_grace:
                pending_grace += 1
                attempts.append(
                    {
                        "resume_attempt_id": attempt_id,
                        "job_id": job_id,
                        "action": "pending_grace",
                        "previous_status": latest_status,
                        "age_seconds": age_seconds,
                        "effective_grace_seconds": effective_grace,
                        "heartbeat_available": heartbeat is not None,
                    }
                )
                continue
            event = record_resume_event(
                repository,
                attempt_id,
                "failed",
                stage="job_reconciliation",
                reason="orphaned_job_missing",
                job_id=job_id,
                previous_status=latest_status,
                configured_grace_seconds=stale_after_seconds,
                effective_grace_seconds=effective_grace,
                age_seconds=age_seconds,
                heartbeat_available=heartbeat is not None,
                heartbeat_at=heartbeat.get("heartbeat_at") if heartbeat else None,
            )
            reconciled += 1
            attempts.append(
                {
                    "resume_attempt_id": attempt_id,
                    "job_id": job_id,
                    "action": "failed",
                    "reason": "orphaned_job_missing",
                    "event": event,
                }
            )
            continue

        rq_status = str(job.get("status") or "")
        terminal = _terminal_event_for_job(job)
        if terminal is None:
            if rq_status in ACTIVE_JOB_STATUSES:
                active += 1
            attempts.append(
                {
                    "resume_attempt_id": attempt_id,
                    "job_id": job_id,
                    "action": "active" if rq_status in ACTIVE_JOB_STATUSES else "unchanged",
                    "rq_status": rq_status,
                }
            )
            continue

        event_status, reason = terminal
        event = record_resume_event(
            repository,
            attempt_id,
            event_status,
            stage="job_reconciliation",
            reason=reason,
            job_id=job_id,
            rq_status=rq_status,
            error=job.get("error"),
            successor_campaign_id=dispatch.get("successor_campaign_id"),
            results_available=bool(
                isinstance(job.get("result"), dict)
                and job["result"].get("results_available")
            ),
        )
        reconciled += 1
        attempts.append(
            {
                "resume_attempt_id": attempt_id,
                "job_id": job_id,
                "action": event_status,
                "reason": reason,
                "event": event,
            }
        )

    return {
        "checked_at": checked_at.isoformat(),
        "scanned": len(attempts),
        "reconciled": reconciled,
        "active": active,
        "pending_grace": pending_grace,
        "stale_after_seconds": stale_after_seconds,
        "attempts": attempts,
    }


def _environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def run_resume_watchdog(
    repository: ArtifactRepository | None = None,
    queue: JobQueue | None = None,
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    queue = queue or RqJobQueue()
    result = reconcile_resume_attempts(
        repository,
        queue,
        limit=_environment_int("THERMOFORM_WATCHDOG_LIMIT", 100, 1, 100),
        stale_after_seconds=_environment_int(
            "THERMOFORM_WATCHDOG_GRACE_SECONDS", 900, 30, 604800
        ),
    )
    watchdog_id = repository.version(
        {
            "checked_at": result["checked_at"],
            "reconciled": result["reconciled"],
            "attempts": result["attempts"],
        },
        "watchdog",
    )
    report = {
        "watchdog_id": watchdog_id,
        "status": "passed",
        "source": "rq_cron",
        "generated_at": datetime.now(UTC).isoformat(),
        **result,
        "downloads": {
            "report": (
                f"/api/v1/cae/{watchdog_id}/artifacts/"
                f"{WATCHDOG_REPORT_FILENAME}"
            )
        },
    }
    repository.save_cae_artifact(
        watchdog_id,
        WATCHDOG_REPORT_FILENAME,
        json.dumps(report, indent=2, sort_keys=True),
    )
    return report
