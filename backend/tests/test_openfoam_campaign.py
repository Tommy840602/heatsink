import json

import pytest
from pydantic import ValidationError

from app.domain.cae import OpenFoamCampaignRequest
from app.domain.models import DesignParameters
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam_campaign import _expected_case_id, run_openfoam_campaign


def _request(**overrides) -> OpenFoamCampaignRequest:
    values = {
        "design": DesignParameters(
            fin_count=20,
            fin_thickness=0.5,
            fin_height=30,
            fin_spacing=1.5,
            air_velocity=2,
        ),
        "target_end_time_s": 0.003,
        "segment_duration_s": 0.001,
        "delta_t_s": 0.0001,
        "write_interval_steps": 1,
        "max_segments": 5,
    }
    values.update(overrides)
    return OpenFoamCampaignRequest(**values)


def _fake_runner(request, repository, calls, expected_case_id, converge_at=None):
    calls.append(request)
    index = len(calls)
    converged = index == converge_at
    solve_run_id = f"solve_{index:012x}"
    return {
        "case_id": expected_case_id,
        "solve_run_id": solve_run_id,
        "resumed_from_run_id": request.resume_from_run_id,
        "status": "passed" if converged else "completed_unconverged",
        "execution_status": "completed",
        "latest_time_s": request.target_end_time_s,
        "target_end_time_s": request.target_end_time_s,
        "checkpoint_created": True,
        "results_available": converged,
        "responses": {"t_max_c": 70, "results_available": converged},
        "response_readiness": {
            "response_sample_count": index,
            "gates": {"energy_balance": converged},
        },
        "downloads": {"checkpoint": f"/checkpoint/{solve_run_id}"},
    }


def test_campaign_chains_checkpoints_until_convergence(tmp_path):
    repository = ArtifactRepository(tmp_path)
    request = _request()
    expected_case_id = _expected_case_id(request, repository)
    calls = []

    result = run_openfoam_campaign(
        request,
        repository,
        solve_runner=lambda solve, repo: _fake_runner(
            solve, repo, calls, expected_case_id, converge_at=3
        ),
    )

    assert result["status"] == "passed"
    assert result["stop_reason"] == "converged"
    assert result["segments_completed"] == 3
    assert result["results_available"] is True
    assert result["numerically_converged"] is True
    assert result["design_result_available"] is False
    assert result["mesh_independence_validated"] is False
    assert calls[0].resume_from_run_id is None
    assert calls[1].resume_from_run_id == "solve_000000000001"
    assert calls[2].resume_from_run_id == "solve_000000000002"
    assert [call.target_end_time_s for call in calls] == pytest.approx(
        [0.001, 0.002, 0.003]
    )


def test_campaign_stops_at_target_without_publishing_unconverged_values(tmp_path):
    repository = ArtifactRepository(tmp_path)
    request = _request(target_end_time_s=0.002)
    expected_case_id = _expected_case_id(request, repository)
    calls = []

    result = run_openfoam_campaign(
        request,
        repository,
        solve_runner=lambda solve, repo: _fake_runner(
            solve, repo, calls, expected_case_id
        ),
    )

    assert result["status"] == "completed_unconverged"
    assert result["stop_reason"] == "target_time_reached"
    assert result["segments_completed"] == 2
    assert result["results_available"] is False
    assert result["next_resume_run_id"] == "solve_000000000002"


def test_campaign_cancellation_is_cooperative_between_checkpoints(tmp_path):
    repository = ArtifactRepository(tmp_path)
    request = _request()
    expected_case_id = _expected_case_id(request, repository)
    calls = []

    result = run_openfoam_campaign(
        request,
        repository,
        solve_runner=lambda solve, repo: _fake_runner(
            solve, repo, calls, expected_case_id
        ),
        should_cancel=lambda: len(calls) >= 1,
    )

    assert result["status"] == "cancelled"
    assert result["stop_reason"] == "cancelled"
    assert result["segments_completed"] == 1
    assert result["next_resume_run_id"] == "solve_000000000001"


def test_campaign_rejects_resume_checkpoint_from_another_case(tmp_path):
    repository = ArtifactRepository(tmp_path)
    resume_id = "solve_deadbeefdead"
    repository.save_cae_artifact(
        resume_id,
        "solve-report.json",
        json.dumps(
            {
                "case_id": "cae_other",
                "latest_time_s": 0.1,
                "results_available": True,
            }
        ),
    )

    result = run_openfoam_campaign(
        _request(resume_from_run_id=resume_id), repository
    )

    assert result["status"] == "failed"
    assert result["stop_reason"] == "resume_case_mismatch"
    assert result["results_available"] is False


def test_campaign_requires_a_response_write_in_each_segment():
    with pytest.raises(ValidationError, match="response write interval"):
        _request(
            segment_duration_s=0.0005,
            delta_t_s=0.0001,
            write_interval_steps=10,
        )
