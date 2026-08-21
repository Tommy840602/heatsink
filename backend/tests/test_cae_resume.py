import json
import zipfile

from fastapi.testclient import TestClient

from app.api import cae as cae_api
from app.domain.cae import OpenFoamCampaignRequest
from app.domain.models import DesignParameters
from app.main import app
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_resume import preview_campaign_resume
from app.services.openfoam_campaign import expected_campaign_case_id
from app.services.openfoam_solve import CHECKPOINT_METADATA


CAMPAIGN_ID = "campaign_000000000010"
SOLVE_ID = "solve_000000000010"


def _design(**overrides) -> DesignParameters:
    values = {
        "fin_count": 20,
        "fin_thickness": 0.5,
        "fin_height": 30,
        "fin_spacing": 1.5,
        "air_velocity": 2.0,
    }
    values.update(overrides)
    return DesignParameters(**values)


def _request(**overrides) -> OpenFoamCampaignRequest:
    values = {
        "design": _design(),
        "mesh_profile": "medium",
        "target_end_time_s": 0.01,
        "segment_duration_s": 0.001,
    }
    values.update(overrides)
    return OpenFoamCampaignRequest(**values)


def _save_resumable_campaign(
    repository: ArtifactRepository,
    request: OpenFoamCampaignRequest,
    latest_time_s: float = 0.003,
) -> None:
    case_id = expected_campaign_case_id(request, repository)
    repository.save_cae_artifact(
        SOLVE_ID,
        "solve-report.json",
        json.dumps(
            {
                "solve_run_id": SOLVE_ID,
                "case_id": case_id,
                "latest_time_s": latest_time_s,
                "checkpoint_created": True,
                "results_available": False,
            }
        ),
    )
    checkpoint = repository.cae_artifact_write_path(SOLVE_ID, "checkpoint.zip")
    with zipfile.ZipFile(checkpoint, "w") as archive:
        archive.writestr(
            CHECKPOINT_METADATA,
            json.dumps(
                {
                    "case_id": case_id,
                    "latest_time_s": latest_time_s,
                    "mesh_validation": {"acceptance_passed": True},
                }
            ),
        )
        archive.writestr("system/controlDict", "control")
    repository.save_cae_artifact(
        CAMPAIGN_ID,
        "campaign-report.json",
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "case_id": case_id,
                "mesh_profile": request.mesh_profile,
                "status": "completed_unconverged",
                "stop_reason": "target_time_reached",
                "latest_time_s": latest_time_s,
                "target_end_time_s": latest_time_s,
                "results_available": False,
                "next_resume_run_id": SOLVE_ID,
                "generated_at": "2026-08-21T05:00:00+00:00",
            }
        ),
    )


def test_resume_preview_returns_validated_job_payload(tmp_path):
    repository = ArtifactRepository(tmp_path)
    request = _request()
    _save_resumable_campaign(repository, request)

    result = preview_campaign_resume(CAMPAIGN_ID, request, repository)

    assert result["resume_ready"] is True
    assert result["reason"] == "ready"
    assert result["checkpoint_available"] is True
    assert result["current_time_s"] == 0.003
    assert result["resume_payload"]["resume_from_run_id"] == SOLVE_ID
    assert result["resume_payload"]["target_end_time_s"] == 0.01


def test_resume_preview_blocks_case_mismatch_and_nonadvancing_target(tmp_path):
    repository = ArtifactRepository(tmp_path)
    original = _request()
    _save_resumable_campaign(repository, original)

    mismatch = preview_campaign_resume(
        CAMPAIGN_ID,
        _request(design=_design(fin_height=31)),
        repository,
    )
    nonadvancing = preview_campaign_resume(
        CAMPAIGN_ID,
        _request(target_end_time_s=0.003),
        repository,
    )

    assert mismatch["resume_ready"] is False
    assert mismatch["reason"] == "case_fingerprint_mismatch"
    assert nonadvancing["resume_ready"] is False
    assert nonadvancing["reason"] == "target_time_not_advanced"


def test_resume_preview_api_returns_preflight_and_404(tmp_path, monkeypatch):
    repository = ArtifactRepository(tmp_path)
    request = _request()
    _save_resumable_campaign(repository, request)
    monkeypatch.setattr(cae_api, "repository", repository)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/cae/campaigns/{CAMPAIGN_ID}/resume-preview",
        json=request.model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.json()["resume_ready"] is True
    assert (
        client.post(
            "/api/v1/cae/campaigns/campaign_deadbeefdead/resume-preview",
            json=request.model_dump(mode="json"),
        ).status_code
        == 404
    )
