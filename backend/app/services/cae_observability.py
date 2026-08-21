import os
from datetime import UTC, datetime
from typing import Any

from app.repositories.artifacts import ArtifactRepository
from app.services.cae_heartbeat import load_resume_heartbeat
from app.services.cae_history import (
    list_resume_dispatches,
    load_latest_resume_watchdog,
)


ATTEMPT_STATUSES = ("queued", "started", "failed", "completed", "cancelled")
TERMINAL_ATTEMPT_STATUSES = {"failed", "completed", "cancelled"}
PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(maximum, max(minimum, value))


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _timestamp(value)
    return max(0.0, (now - parsed).total_seconds()) if parsed else None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _attempt_status(attempt: dict[str, Any]) -> str:
    events = attempt.get("events")
    if isinstance(events, list) and events:
        status = str(events[-1].get("status") or "")
    else:
        status = str(attempt.get("status") or attempt.get("status_at_dispatch") or "")
    if status.startswith("completed") or status == "finished":
        return "completed"
    if status in ATTEMPT_STATUSES:
        return status
    return "queued"


def build_cae_observability_snapshot(
    repository: ArtifactRepository,
    *,
    now: datetime | None = None,
    heartbeat_stale_seconds: int | None = None,
    watchdog_stale_seconds: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    heartbeat_threshold = heartbeat_stale_seconds or _environment_int(
        "THERMOFORM_HEARTBEAT_STALE_SECONDS", 120, 30, 604800
    )
    watchdog_threshold = watchdog_stale_seconds or _environment_int(
        "THERMOFORM_WATCHDOG_STALE_SECONDS", 180, 30, 604800
    )
    attempt_limit = limit or _environment_int(
        "THERMOFORM_OBSERVABILITY_ATTEMPT_LIMIT", 1000, 1, 10000
    )
    attempts = list_resume_dispatches(repository, attempt_limit)
    status_counts = {status: 0 for status in ATTEMPT_STATUSES}
    retry_attempts = 0
    failed_retry_attempts = 0
    orphan_repairs = 0
    active_heartbeats = 0
    stale_heartbeats = 0
    heartbeat_ages: list[float] = []

    for attempt in attempts:
        status = _attempt_status(attempt)
        status_counts[status] += 1
        is_retry = bool(attempt.get("retry_of_attempt_id")) or _safe_int(
            attempt.get("retry_index")
        ) > 0
        retry_attempts += int(is_retry)
        failed_retry_attempts += int(is_retry and status == "failed")
        events = attempt.get("events")
        if isinstance(events, list):
            orphan_repairs += sum(
                1
                for event in events
                if event.get("reason") == "orphaned_job_missing"
            )
        if status in TERMINAL_ATTEMPT_STATUSES:
            continue
        attempt_id = str(attempt.get("resume_attempt_id") or "")
        heartbeat = load_resume_heartbeat(repository, attempt_id)
        if not heartbeat or heartbeat.get("active") is not True:
            continue
        age = _age_seconds(heartbeat.get("heartbeat_at"), checked_at)
        if age is None:
            continue
        active_heartbeats += 1
        heartbeat_ages.append(age)
        stale_heartbeats += int(age > heartbeat_threshold)

    watchdog = load_latest_resume_watchdog(repository)
    watchdog_age = (
        _age_seconds(watchdog.get("checked_at") or watchdog.get("generated_at"), checked_at)
        if watchdog
        else None
    )
    watchdog_present = watchdog is not None
    watchdog_stale = (
        not watchdog_present
        or watchdog_age is None
        or watchdog_age > watchdog_threshold
    )
    watchdog_timestamp = (
        _timestamp(watchdog.get("checked_at") or watchdog.get("generated_at"))
        if watchdog
        else None
    )
    watchdog_attempts = watchdog.get("attempts") if watchdog else None
    watchdog_orphan_repairs = (
        sum(
            1
            for attempt in watchdog_attempts
            if isinstance(attempt, dict)
            and attempt.get("reason") == "orphaned_job_missing"
        )
        if isinstance(watchdog_attempts, list)
        else 0
    )
    if not watchdog_present:
        health = "unknown"
    elif watchdog_stale or stale_heartbeats:
        health = "degraded"
    else:
        health = "healthy"

    return {
        "checked_at": checked_at.isoformat(),
        "status": health,
        "thresholds": {
            "heartbeat_stale_seconds": heartbeat_threshold,
            "watchdog_stale_seconds": watchdog_threshold,
        },
        "attempts": {
            "total": len(attempts),
            "by_status": status_counts,
            "retries": retry_attempts,
            "failed_retries": failed_retry_attempts,
            "orphan_repairs": orphan_repairs,
            "truncated": len(attempts) == attempt_limit,
        },
        "heartbeats": {
            "active": active_heartbeats,
            "stale": stale_heartbeats,
            "max_age_seconds": max(heartbeat_ages, default=0.0),
        },
        "watchdog": {
            "present": watchdog_present,
            "stale": watchdog_stale,
            "age_seconds": watchdog_age,
            "last_success_timestamp": watchdog_timestamp.timestamp()
            if watchdog_timestamp
            else 0.0,
            "watchdog_id": watchdog.get("watchdog_id") if watchdog else None,
            "checked_at": watchdog.get("checked_at") if watchdog else None,
            "reconciled": _safe_int(watchdog.get("reconciled")) if watchdog else 0,
            "orphan_repairs": watchdog_orphan_repairs,
            "active": _safe_int(watchdog.get("active")) if watchdog else 0,
            "pending_grace": _safe_int(watchdog.get("pending_grace"))
            if watchdog
            else 0,
        },
    }


def render_prometheus_metrics(snapshot: dict[str, Any]) -> str:
    attempts = snapshot["attempts"]
    heartbeats = snapshot["heartbeats"]
    watchdog = snapshot["watchdog"]
    lines = [
        "# HELP thermoform_cae_resume_attempts Durable CAE resume attempts discovered in artifact storage.",
        "# TYPE thermoform_cae_resume_attempts gauge",
        f'thermoform_cae_resume_attempts {attempts["total"]}',
        "# HELP thermoform_cae_resume_attempts_by_status Durable CAE resume attempts by lifecycle status.",
        "# TYPE thermoform_cae_resume_attempts_by_status gauge",
    ]
    lines.extend(
        f'thermoform_cae_resume_attempts_by_status{{status="{status}"}} {attempts["by_status"][status]}'
        for status in ATTEMPT_STATUSES
    )
    lines.extend(
        [
            "# HELP thermoform_cae_resume_retry_attempts Durable retry attempts.",
            "# TYPE thermoform_cae_resume_retry_attempts gauge",
            f'thermoform_cae_resume_retry_attempts {attempts["retries"]}',
            "# HELP thermoform_cae_resume_failed_retry_attempts Durable retry attempts currently failed.",
            "# TYPE thermoform_cae_resume_failed_retry_attempts gauge",
            f'thermoform_cae_resume_failed_retry_attempts {attempts["failed_retries"]}',
            "# HELP thermoform_cae_resume_orphan_repairs Durable attempts repaired after their RQ job disappeared.",
            "# TYPE thermoform_cae_resume_orphan_repairs gauge",
            f'thermoform_cae_resume_orphan_repairs {attempts["orphan_repairs"]}',
            "# HELP thermoform_cae_resume_active_heartbeats Active durable resume heartbeats.",
            "# TYPE thermoform_cae_resume_active_heartbeats gauge",
            f'thermoform_cae_resume_active_heartbeats {heartbeats["active"]}',
            "# HELP thermoform_cae_resume_stale_heartbeats Active heartbeats older than the configured lease.",
            "# TYPE thermoform_cae_resume_stale_heartbeats gauge",
            f'thermoform_cae_resume_stale_heartbeats {heartbeats["stale"]}',
            "# HELP thermoform_cae_resume_heartbeat_max_age_seconds Age of the oldest active heartbeat.",
            "# TYPE thermoform_cae_resume_heartbeat_max_age_seconds gauge",
            f'thermoform_cae_resume_heartbeat_max_age_seconds {heartbeats["max_age_seconds"]:.3f}',
            "# HELP thermoform_cae_watchdog_present Whether a durable watchdog report exists.",
            "# TYPE thermoform_cae_watchdog_present gauge",
            f'thermoform_cae_watchdog_present {int(watchdog["present"])}',
            "# HELP thermoform_cae_watchdog_last_success_timestamp_seconds Unix timestamp of the latest durable watchdog audit.",
            "# TYPE thermoform_cae_watchdog_last_success_timestamp_seconds gauge",
            f'thermoform_cae_watchdog_last_success_timestamp_seconds {watchdog["last_success_timestamp"]:.3f}',
            "# HELP thermoform_cae_watchdog_age_seconds Age of the latest durable watchdog audit.",
            "# TYPE thermoform_cae_watchdog_age_seconds gauge",
            f'thermoform_cae_watchdog_age_seconds {(watchdog["age_seconds"] or 0.0):.3f}',
            "# HELP thermoform_cae_watchdog_last_reconciled_attempts Attempts repaired by the latest watchdog audit.",
            "# TYPE thermoform_cae_watchdog_last_reconciled_attempts gauge",
            f'thermoform_cae_watchdog_last_reconciled_attempts {watchdog["reconciled"]}',
            "# HELP thermoform_cae_watchdog_last_orphan_repairs Orphaned attempts repaired by the latest watchdog audit.",
            "# TYPE thermoform_cae_watchdog_last_orphan_repairs gauge",
            f'thermoform_cae_watchdog_last_orphan_repairs {watchdog["orphan_repairs"]}',
            "# HELP thermoform_cae_watchdog_last_active_attempts Active attempts seen by the latest watchdog audit.",
            "# TYPE thermoform_cae_watchdog_last_active_attempts gauge",
            f'thermoform_cae_watchdog_last_active_attempts {watchdog["active"]}',
            "# HELP thermoform_cae_watchdog_last_pending_grace_attempts Missing jobs still within their recovery grace period.",
            "# TYPE thermoform_cae_watchdog_last_pending_grace_attempts gauge",
            f'thermoform_cae_watchdog_last_pending_grace_attempts {watchdog["pending_grace"]}',
            "# HELP thermoform_cae_observability_healthy Whether watchdog and active heartbeat leases are healthy.",
            "# TYPE thermoform_cae_observability_healthy gauge",
            f'thermoform_cae_observability_healthy {int(snapshot["status"] == "healthy")}',
        ]
    )
    return "\n".join(lines) + "\n"
