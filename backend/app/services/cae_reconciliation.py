from datetime import UTC, datetime
from typing import Any

from rq.exceptions import NoSuchJobError

from app.repositories.artifacts import ArtifactRepository
from app.services.cae_history import list_resume_dispatches, list_resume_events
from app.services.cae_resume import record_resume_event
from app.services.jobs import JobQueue


TERMINAL_EVENT_STATUSES = {"failed", "completed", "cancelled"}
ACTIVE_JOB_STATUSES = {"queued", "deferred", "scheduled", "started"}
ORPHAN_RUNTIME_BUFFER_SECONDS = 300


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
            timestamp = (
                latest_event.get("generated_at")
                if latest_event
                else dispatch.get("generated_at")
            )
            age_seconds = _age_seconds(timestamp, checked_at)
            effective_grace = _effective_grace_seconds(
                dispatch, stale_after_seconds
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
