import importlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from rq import cron

from app.api import cae as cae_api
from app.main import app
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_heartbeat import (
    ResumeAttemptHeartbeat,
    load_resume_heartbeat,
    write_resume_heartbeat,
)
from app.services.cae_history import load_latest_resume_watchdog
from app.services.cae_reconciliation import run_resume_watchdog


class EmptyQueue:
    def __init__(self):
        self.calls = []

    def get(self, job_id):
        self.calls.append(job_id)
        return {"job_id": job_id, "status": "started", "stage": "solving"}


def test_heartbeat_is_atomically_replaced_and_periodically_refreshed(tmp_path):
    repository = ArtifactRepository(tmp_path)
    attempt_id = "resume_000000000020"
    heartbeat = ResumeAttemptHeartbeat(
        repository,
        attempt_id,
        interval_seconds=0.01,
        job_id=f"job_{attempt_id}",
    )

    heartbeat.start("campaign_execution", segment_current=1)
    time.sleep(0.03)
    heartbeat.update("completed", active=False, segment_current=2)
    heartbeat.close()

    stored = load_resume_heartbeat(repository, attempt_id)
    assert stored is not None
    assert stored["stage"] == "completed"
    assert stored["active"] is False
    assert stored["segment_current"] == 2
    assert stored["heartbeat_interval_seconds"] == 0.01
    assert not repository.cae_artifact_write_path(
        attempt_id, ".resume-heartbeat.json.tmp"
    ).exists()


def test_watchdog_persists_a_durable_report_and_api_returns_latest(
    tmp_path, monkeypatch
):
    repository = ArtifactRepository(tmp_path)
    queue = EmptyQueue()

    first = run_resume_watchdog(repository, queue)
    time.sleep(0.001)
    second = run_resume_watchdog(repository, queue)

    assert first["watchdog_id"].startswith("watchdog_")
    assert second["watchdog_id"] != first["watchdog_id"]
    assert second["source"] == "rq_cron"
    assert load_latest_resume_watchdog(repository)["watchdog_id"] == second[
        "watchdog_id"
    ]
    monkeypatch.setattr(cae_api, "repository", repository)
    response = TestClient(app).get("/api/v1/cae/resume-watchdog")
    assert response.status_code == 200
    assert response.json()["watchdog"]["watchdog_id"] == second["watchdog_id"]


def test_cron_config_registers_watchdog_on_general_queue(monkeypatch):
    monkeypatch.setenv("THERMOFORM_WATCHDOG_INTERVAL_SECONDS", "45")
    cron._job_data_registry.clear()
    try:
        module = importlib.import_module("app.cron_config")
        importlib.reload(module)
        registrations = list(cron._job_data_registry)
    finally:
        cron._job_data_registry.clear()

    registration = registrations[-1]
    assert registration["func"] is run_resume_watchdog
    assert registration["queue_name"] == "thermoform"
    assert registration["interval"] == 45
    assert registration["name"] == "cae-resume-watchdog"


def test_compose_runs_rq_cron_watchdog_service():
    compose = Path(__file__).parents[2].joinpath("docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "watchdog:" in compose
    assert "rq cron app.cron_config" in compose
    assert "THERMOFORM_WATCHDOG_INTERVAL_SECONDS: 60" in compose
