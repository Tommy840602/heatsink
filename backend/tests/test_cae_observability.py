import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api import metrics as metrics_api
from app.main import app
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_observability import (
    build_cae_observability_snapshot,
    render_prometheus_metrics,
)


def _save_attempt(
    repository: ArtifactRepository,
    suffix: str,
    timestamp: datetime,
    *,
    retry: bool = False,
    status: str = "queued",
    reason: str | None = None,
) -> str:
    attempt_id = f"resume_{suffix}"
    dispatch = {
        "resume_attempt_id": attempt_id,
        "parent_campaign_id": "campaign_000000000001",
        "successor_campaign_id": f"campaign_{suffix}",
        "checkpoint_run_id": "solve_000000000001",
        "job_id": f"job_{attempt_id}",
        "queue": "thermoform-cae",
        "status_at_dispatch": "queued",
        "generated_at": timestamp.isoformat(),
        "request": {},
        "retry_of_attempt_id": "resume_000000000001" if retry else None,
        "retry_index": 1 if retry else 0,
    }
    repository.save_cae_artifact(
        attempt_id, "resume-dispatch.json", json.dumps(dispatch)
    )
    event = {
        "resume_attempt_id": attempt_id,
        "status": status,
        "generated_at": timestamp.isoformat(),
    }
    if reason:
        event["reason"] = reason
    repository.save_cae_artifact(
        attempt_id, f"resume-event-{status}.json", json.dumps(event)
    )
    return attempt_id


def _save_watchdog(
    repository: ArtifactRepository, timestamp: datetime
) -> None:
    watchdog_id = "watchdog_000000000001"
    repository.save_cae_artifact(
        watchdog_id,
        "resume-watchdog-report.json",
        json.dumps(
            {
                "watchdog_id": watchdog_id,
                "status": "passed",
                "checked_at": timestamp.isoformat(),
                "generated_at": timestamp.isoformat(),
                "reconciled": 1,
                "active": 2,
                "pending_grace": 3,
            }
        ),
    )


def test_snapshot_aggregates_durable_resume_health(tmp_path):
    repository = ArtifactRepository(tmp_path)
    now = datetime(2026, 8, 21, 4, 0, tzinfo=UTC)
    active_id = _save_attempt(
        repository, "000000000030", now - timedelta(minutes=4)
    )
    _save_attempt(
        repository,
        "000000000031",
        now - timedelta(minutes=3),
        retry=True,
        status="failed",
        reason="orphaned_job_missing",
    )
    repository.save_cae_artifact(
        active_id,
        "resume-heartbeat.json",
        json.dumps(
            {
                "resume_attempt_id": active_id,
                "stage": "campaign_execution",
                "active": True,
                "heartbeat_at": (now - timedelta(seconds=121)).isoformat(),
            }
        ),
    )
    _save_watchdog(repository, now - timedelta(seconds=60))

    snapshot = build_cae_observability_snapshot(
        repository,
        now=now,
        heartbeat_stale_seconds=120,
        watchdog_stale_seconds=180,
    )

    assert snapshot["status"] == "degraded"
    assert snapshot["attempts"]["total"] == 2
    assert snapshot["attempts"]["by_status"]["queued"] == 1
    assert snapshot["attempts"]["by_status"]["failed"] == 1
    assert snapshot["attempts"]["retries"] == 1
    assert snapshot["attempts"]["failed_retries"] == 1
    assert snapshot["attempts"]["orphan_repairs"] == 1
    assert snapshot["heartbeats"] == {
        "active": 1,
        "stale": 1,
        "max_age_seconds": 121.0,
    }
    assert snapshot["watchdog"]["present"] is True
    assert snapshot["watchdog"]["stale"] is False
    assert snapshot["watchdog"]["age_seconds"] == 60.0
    assert snapshot["watchdog"]["reconciled"] == 1


def test_missing_watchdog_is_explicit_and_metrics_are_prometheus_text(tmp_path):
    snapshot = build_cae_observability_snapshot(
        ArtifactRepository(tmp_path),
        now=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
    )
    metrics = render_prometheus_metrics(snapshot)

    assert snapshot["status"] == "unknown"
    assert snapshot["watchdog"]["present"] is False
    assert "# TYPE thermoform_cae_resume_attempts gauge" in metrics
    assert 'thermoform_cae_resume_attempts_by_status{status="failed"} 0' in metrics
    assert "thermoform_cae_watchdog_present 0" in metrics
    assert "thermoform_cae_observability_healthy 0" in metrics


def test_observability_json_and_metrics_endpoints_share_durable_state(
    tmp_path, monkeypatch
):
    repository = ArtifactRepository(tmp_path)
    now = datetime.now(UTC)
    _save_watchdog(repository, now)
    monkeypatch.setattr(metrics_api, "repository", repository)
    client = TestClient(app)

    observability = client.get("/api/v1/cae/observability")
    metrics = client.get("/metrics")

    assert observability.status_code == 200
    assert observability.json()["status"] == "healthy"
    assert observability.json()["watchdog"]["watchdog_id"] == (
        "watchdog_000000000001"
    )
    assert metrics.status_code == 200
    assert metrics.headers["content-type"] == (
        "text/plain; version=0.0.4; charset=utf-8"
    )
    assert "thermoform_cae_watchdog_present 1" in metrics.text
