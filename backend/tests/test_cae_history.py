import json

from fastapi.testclient import TestClient

from app.api import cae as cae_api
from app.main import app
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_history import (
    list_campaign_reports,
    list_mesh_study_reports,
    list_resume_dispatches,
    load_campaign_report,
    load_mesh_study_report,
)


def _save_campaign(
    repository: ArtifactRepository,
    suffix: str,
    profile: str,
    generated_at: str,
) -> str:
    campaign_id = f"campaign_{suffix}"
    repository.save_cae_artifact(
        campaign_id,
        "campaign-report.json",
        json.dumps(
            {
                "campaign_id": campaign_id,
                "case_id": f"cae_{suffix}",
                "mesh_profile": profile,
                "study_fingerprint": "mesh-study_shared",
                "status": "passed",
                "stop_reason": "converged",
                "segments_completed": 3,
                "segments": [{"index": 1}],
                "latest_time_s": 0.003,
                "target_end_time_s": 0.01,
                "results_available": True,
                "numerically_converged": True,
                "mesh_independence_validated": False,
                "design_result_available": False,
                "next_resume_run_id": f"solve_{suffix}",
                "generated_at": generated_at,
                "downloads": {"report": f"/{campaign_id}"},
            }
        ),
    )
    return campaign_id


def _save_study(repository: ArtifactRepository, suffix: str) -> str:
    study_id = f"meshstudy_{suffix}"
    repository.save_cae_artifact(
        study_id,
        "mesh-study-report.json",
        json.dumps(
            {
                "mesh_study_id": study_id,
                "status": "passed",
                "campaign_ids": {
                    "coarse": "campaign_000000000001",
                    "medium": "campaign_000000000002",
                    "fine": "campaign_000000000003",
                },
                "campaigns_validated": True,
                "validation_errors": [],
                "comparisons": {},
                "limits": {},
                "gates": {},
                "mesh_independence_validated": True,
                "results_available": True,
                "design_result_available": True,
                "recommended_profile": "fine",
                "generated_at": "2026-08-21T03:00:00+00:00",
                "downloads": {"report": f"/{study_id}"},
                "notice": "passed",
            }
        ),
    )
    return study_id


def _save_resume_dispatch(
    repository: ArtifactRepository,
    suffix: str,
    successor_campaign_id: str,
) -> str:
    attempt_id = f"resume_{suffix}"
    repository.save_cae_artifact(
        attempt_id,
        "resume-dispatch.json",
        json.dumps(
            {
                "resume_attempt_id": attempt_id,
                "parent_campaign_id": "campaign_000000000001",
                "successor_campaign_id": successor_campaign_id,
                "checkpoint_run_id": "solve_000000000001",
                "checkpoint_time_s": 0.003,
                "requested_target_end_time_s": 0.01,
                "job_id": f"job_{attempt_id}",
                "queue": "thermoform-cae",
                "status_at_dispatch": "queued",
                "generated_at": "2026-08-21T05:00:00+00:00",
            }
        ),
    )
    return attempt_id


def test_cae_history_lists_summaries_and_loads_full_reports(tmp_path):
    repository = ArtifactRepository(tmp_path)
    older = _save_campaign(
        repository, "000000000001", "coarse", "2026-08-21T01:00:00+00:00"
    )
    newer = _save_campaign(
        repository, "000000000002", "medium", "2026-08-21T02:00:00+00:00"
    )
    study_id = _save_study(repository, "000000000003")
    attempt_id = _save_resume_dispatch(repository, "000000000006", newer)
    repository.save_cae_artifact(
        "campaign_deadbeefdead", "campaign-report.json", "not json"
    )

    campaigns = list_campaign_reports(repository)
    studies = list_mesh_study_reports(repository)
    attempts = list_resume_dispatches(repository)

    assert [item["campaign_id"] for item in campaigns] == [newer, older]
    assert "segments" not in campaigns[0]
    assert load_campaign_report(repository, newer)["segments"] == [{"index": 1}]
    assert studies[0]["mesh_study_id"] == study_id
    assert load_mesh_study_report(repository, study_id)["design_result_available"] is True
    assert attempts[0]["resume_attempt_id"] == attempt_id
    assert attempts[0]["successor_available"] is True
    assert attempts[0]["status"] == "passed"


def test_cae_history_api_supports_reconnect_and_rejects_unknown_ids(
    tmp_path, monkeypatch
):
    repository = ArtifactRepository(tmp_path)
    campaign_id = _save_campaign(
        repository, "000000000004", "fine", "2026-08-21T04:00:00+00:00"
    )
    study_id = _save_study(repository, "000000000005")
    _save_resume_dispatch(repository, "000000000007", campaign_id)
    monkeypatch.setattr(cae_api, "repository", repository)
    client = TestClient(app)

    campaigns = client.get("/api/v1/cae/campaigns?limit=10")
    campaign = client.get(f"/api/v1/cae/campaigns/{campaign_id}")
    studies = client.get("/api/v1/cae/mesh-studies")
    attempts = client.get("/api/v1/cae/resume-attempts")
    study = client.get(f"/api/v1/cae/mesh-studies/{study_id}")

    assert campaigns.status_code == 200
    assert campaigns.json()["count"] == 1
    assert campaign.json()["segments"] == [{"index": 1}]
    assert studies.json()["count"] == 1
    assert attempts.status_code == 200
    assert attempts.json()["count"] == 1
    assert attempts.json()["resume_attempts"][0]["successor_available"] is True
    assert study.json()["design_result_available"] is True
    assert client.get("/api/v1/cae/campaigns/not-a-campaign").status_code == 404
    assert client.get("/api/v1/cae/mesh-studies/not-a-study").status_code == 404
