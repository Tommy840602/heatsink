from datetime import UTC, datetime

from fastapi.testclient import TestClient
from rq.exceptions import NoSuchJobError

from app.main import app
from app.services.jobs import (
    CAE_QUEUE_NAME,
    DEFAULT_QUEUE_NAME,
    RqJobQueue,
    get_job_queue,
    queue_name_for_task,
)


class FakeQueue:
    def enqueue(self, task, payload, metadata=None):
        return {
            "job_id": "job_test123",
            "task": task,
            "status": "queued",
            "created_at": datetime.now(UTC).isoformat(),
            "started_at": None,
            "ended_at": None,
            "result": None,
            "error": None,
            "lineage": metadata.get("lineage") if metadata else None,
        }

    def get(self, job_id):
        return {
            "job_id": job_id,
            "task": "cae",
            "status": "finished",
            "created_at": None,
            "started_at": None,
            "ended_at": None,
            "result": {"case_generated": True, "results_available": False},
            "error": None,
        }

    def cancel(self, job_id):
        return {
            "job_id": job_id,
            "task": "cae_campaign",
            "status": "started",
            "created_at": None,
            "started_at": None,
            "ended_at": None,
            "result": None,
            "error": None,
            "progress": 40,
            "stage": "cancel_requested",
            "queue": CAE_QUEUE_NAME,
            "cancel_requested": True,
        }


def test_job_api_returns_202_and_exposes_completed_result():
    app.dependency_overrides[get_job_queue] = lambda: FakeQueue()
    try:
        client = TestClient(app)
        queued = client.post("/api/v1/jobs", json={"task": "cae", "payload": {}})
        assert queued.status_code == 202
        assert queued.json()["status"] == "queued"

        finished = client.get("/api/v1/jobs/job_test123")
        assert finished.status_code == 200
        assert finished.json()["result"]["results_available"] is False

        cancelled = client.post("/api/v1/jobs/job_test123/cancel")
        assert cancelled.status_code == 202
        assert cancelled.json()["cancel_requested"] is True
        assert cancelled.json()["stage"] == "cancel_requested"
    finally:
        app.dependency_overrides.clear()


def test_cae_benchmark_isolated_queue_routing():
    assert queue_name_for_task("cae_benchmark") == CAE_QUEUE_NAME
    assert queue_name_for_task("cae") == CAE_QUEUE_NAME
    assert queue_name_for_task("cae_mesh") == CAE_QUEUE_NAME
    assert queue_name_for_task("cae_smoke") == CAE_QUEUE_NAME
    assert queue_name_for_task("cae_solve") == CAE_QUEUE_NAME
    assert queue_name_for_task("cae_campaign") == CAE_QUEUE_NAME
    assert queue_name_for_task("cae_mesh_study") == CAE_QUEUE_NAME
    assert queue_name_for_task("phase1") == DEFAULT_QUEUE_NAME


def test_rq_enqueue_once_locks_deterministic_job_id_and_reuses_it(monkeypatch):
    class FakeLock:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeConnection:
        def __init__(self):
            self.lock_keys = []

        def lock(self, key, **_options):
            self.lock_keys.append(key)
            return FakeLock()

    queue = object.__new__(RqJobQueue)
    queue.connection = FakeConnection()
    created = []
    existing_job = object()
    fetch_count = 0

    def fake_fetch(_job_id, connection):
        nonlocal fetch_count
        fetch_count += 1
        assert connection is queue.connection
        if fetch_count == 1:
            raise NoSuchJobError
        return existing_job

    def fake_enqueue(task, payload, metadata, *, job_id):
        created.append((task, payload, metadata, job_id))
        return {"job_id": job_id, "status": "queued"}

    monkeypatch.setattr("app.services.jobs.Job.fetch", fake_fetch)
    monkeypatch.setattr(queue, "_enqueue", fake_enqueue)
    monkeypatch.setattr(
        queue,
        "_snapshot",
        lambda job, refresh: {
            "job_id": "job_resume_deadbeefdead",
            "status": "queued",
        },
    )

    first = queue.enqueue_once("cae_campaign", {}, "resume_deadbeefdead")
    duplicate = queue.enqueue_once("cae_campaign", {}, "resume_deadbeefdead")

    assert created[0][3] == "job_resume_deadbeefdead"
    assert first["deduplicated"] is False
    assert duplicate["deduplicated"] is True
    assert queue.connection.lock_keys == [
        "thermoform:enqueue:resume_deadbeefdead",
        "thermoform:enqueue:resume_deadbeefdead",
    ]
