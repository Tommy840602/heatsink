import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from rq.exceptions import NoSuchJobError

from app.api import cae as cae_api
from app.main import app
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_history import list_resume_dispatches, list_resume_events
from app.services.cae_reconciliation import reconcile_resume_attempts
from app.services.jobs import get_job_queue


class SnapshotQueue:
    def __init__(self, snapshots=None):
        self.snapshots = snapshots or {}
        self.calls = []

    def get(self, job_id):
        self.calls.append(job_id)
        if job_id not in self.snapshots:
            raise NoSuchJobError
        return self.snapshots[job_id]


def _save_attempt(
    repository: ArtifactRepository,
    suffix: str,
    *,
    generated_at: str | None = None,
    segment_runtime_seconds: int = 30,
    max_total_runtime_seconds: int = 60,
) -> tuple[str, str]:
    attempt_id = f"resume_{suffix}"
    job_id = f"job_{attempt_id}"
    timestamp = generated_at or datetime.now(UTC).isoformat()
    repository.save_cae_artifact(
        attempt_id,
        "resume-dispatch.json",
        json.dumps(
            {
                "resume_attempt_id": attempt_id,
                "parent_campaign_id": "campaign_000000000001",
                "successor_campaign_id": f"campaign_{suffix}",
                "checkpoint_run_id": "solve_000000000001",
                "checkpoint_time_s": 0.003,
                "requested_target_end_time_s": 0.01,
                "request": {
                    "design": {
                        "fin_count": 20,
                        "fin_thickness": 0.5,
                        "fin_height": 30,
                        "fin_spacing": 1.5,
                        "air_velocity": 2.0,
                    },
                    "mesh_profile": "medium",
                    "target_end_time_s": 0.01,
                    "segment_duration_s": 0.001,
                    "segment_runtime_seconds": segment_runtime_seconds,
                    "max_total_runtime_seconds": max_total_runtime_seconds,
                },
                "job_id": job_id,
                "queue": "thermoform-cae",
                "status_at_dispatch": "queued",
                "generated_at": timestamp,
            }
        ),
    )
    repository.save_cae_artifact(
        attempt_id,
        "resume-event-queued.json",
        json.dumps(
            {
                "resume_attempt_id": attempt_id,
                "status": "queued",
                "job_id": job_id,
                "generated_at": timestamp,
            }
        ),
    )
    return attempt_id, job_id


def test_missing_job_is_failed_only_after_grace_and_is_idempotent(tmp_path):
    repository = ArtifactRepository(tmp_path)
    attempt_id, job_id = _save_attempt(repository, "000000000010")
    queue = SnapshotQueue()
    started = datetime.now(UTC)

    pending = reconcile_resume_attempts(
        repository,
        queue,
        stale_after_seconds=900,
        now=started,
    )
    reconciled = reconcile_resume_attempts(
        repository,
        queue,
        stale_after_seconds=900,
        now=started + timedelta(seconds=901),
    )
    duplicate = reconcile_resume_attempts(
        repository,
        queue,
        stale_after_seconds=900,
        now=started + timedelta(seconds=902),
    )

    assert pending["pending_grace"] == 1
    assert pending["reconciled"] == 0
    assert reconciled["reconciled"] == 1
    assert reconciled["attempts"][0]["reason"] == "orphaned_job_missing"
    assert duplicate["reconciled"] == 0
    assert queue.calls == [job_id, job_id]
    events = list_resume_events(repository, attempt_id)
    assert [event["status"] for event in events] == ["queued", "failed"]
    assert list_resume_dispatches(repository)[0]["retry_allowed"] is True


def test_rq_terminal_snapshots_repair_missing_terminal_events(tmp_path):
    repository = ArtifactRepository(tmp_path)
    failed_id, failed_job = _save_attempt(repository, "000000000011")
    finished_id, finished_job = _save_attempt(repository, "000000000012")
    queue = SnapshotQueue(
        {
            failed_job: {
                "job_id": failed_job,
                "status": "failed",
                "stage": "campaign_execution",
                "error": "worker lost",
            },
            finished_job: {
                "job_id": finished_job,
                "status": "finished",
                "result": {
                    "status": "completed_unconverged",
                    "results_available": False,
                },
            },
        }
    )

    result = reconcile_resume_attempts(repository, queue)

    assert result["reconciled"] == 2
    assert {attempt["action"] for attempt in result["attempts"]} == {
        "failed",
        "completed",
    }
    assert [event["status"] for event in list_resume_events(repository, failed_id)] == [
        "queued",
        "failed",
    ]
    assert [
        event["status"] for event in list_resume_events(repository, finished_id)
    ] == ["queued", "completed"]


def test_missing_job_grace_covers_campaign_and_final_segment_budget(tmp_path):
    repository = ArtifactRepository(tmp_path)
    attempt_id, _job_id = _save_attempt(
        repository,
        "000000000016",
        segment_runtime_seconds=300,
        max_total_runtime_seconds=1800,
    )
    queue = SnapshotQueue()
    started = datetime.now(UTC)

    pending = reconcile_resume_attempts(
        repository,
        queue,
        stale_after_seconds=30,
        now=started + timedelta(seconds=2399),
    )
    reconciled = reconcile_resume_attempts(
        repository,
        queue,
        stale_after_seconds=30,
        now=started + timedelta(seconds=2401),
    )

    assert pending["pending_grace"] == 1
    assert pending["attempts"][0]["effective_grace_seconds"] == 2400
    assert reconciled["reconciled"] == 1
    assert list_resume_events(repository, attempt_id)[-1]["status"] == "failed"


def test_active_rq_job_remains_unchanged(tmp_path):
    repository = ArtifactRepository(tmp_path)
    attempt_id, job_id = _save_attempt(repository, "000000000013")
    queue = SnapshotQueue(
        {job_id: {"job_id": job_id, "status": "started", "stage": "solving"}}
    )

    result = reconcile_resume_attempts(repository, queue)

    assert result["active"] == 1
    assert result["reconciled"] == 0
    assert [event["status"] for event in list_resume_events(repository, attempt_id)] == [
        "queued"
    ]


def test_successor_report_repairs_event_without_consulting_expired_job(tmp_path):
    repository = ArtifactRepository(tmp_path)
    attempt_id, _job_id = _save_attempt(repository, "000000000015")
    successor_id = "campaign_000000000015"
    repository.save_cae_artifact(
        successor_id,
        "campaign-report.json",
        json.dumps(
            {
                "campaign_id": successor_id,
                "status": "completed_unconverged",
                "stop_reason": "target_time_reached",
                "results_available": False,
                "generated_at": datetime.now(UTC).isoformat(),
            }
        ),
    )
    queue = SnapshotQueue()

    result = reconcile_resume_attempts(repository, queue)

    assert result["reconciled"] == 1
    assert result["attempts"][0]["reason"] == "successor_report_available"
    assert queue.calls == []
    assert [event["status"] for event in list_resume_events(repository, attempt_id)] == [
        "queued",
        "completed",
    ]


def test_reconciliation_api_repairs_old_orphaned_attempt(tmp_path, monkeypatch):
    repository = ArtifactRepository(tmp_path)
    attempt_id, _job_id = _save_attempt(
        repository,
        "000000000014",
        generated_at="2026-08-20T00:00:00+00:00",
    )
    queue = SnapshotQueue()
    monkeypatch.setattr(cae_api, "repository", repository)
    app.dependency_overrides[get_job_queue] = lambda: queue
    try:
        response = TestClient(app).post(
            "/api/v1/cae/resume-attempts/reconcile?stale_after_seconds=30"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["reconciled"] == 1
    assert list_resume_dispatches(repository)[0]["status"] == "failed"
    assert list_resume_events(repository, attempt_id)[-1]["reason"] == (
        "orphaned_job_missing"
    )
