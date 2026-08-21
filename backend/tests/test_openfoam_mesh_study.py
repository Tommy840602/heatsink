import json

from app.domain.cae import OpenFoamMeshIndependenceRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam_mesh_study import evaluate_mesh_independence


CAMPAIGN_IDS = {
    "coarse": "campaign_000000000001",
    "medium": "campaign_000000000002",
    "fine": "campaign_000000000003",
}


def _save_campaigns(repository, responses, *, converged=True):
    for profile, campaign_id in CAMPAIGN_IDS.items():
        repository.save_cae_artifact(
            campaign_id,
            "campaign-report.json",
            json.dumps(
                {
                    "campaign_id": campaign_id,
                    "mesh_profile": profile,
                    "study_fingerprint": "mesh-study_samecase",
                    "results_available": converged,
                    "responses": responses[profile],
                }
            ),
        )


def test_mesh_study_publishes_fine_result_only_after_all_gates_pass(tmp_path):
    repository = ArtifactRepository(tmp_path)
    _save_campaigns(
        repository,
        {
            "coarse": {"t_max_c": 72.0, "pressure_drop_pa": 12.0},
            "medium": {"t_max_c": 70.0, "pressure_drop_pa": 10.2},
            "fine": {"t_max_c": 69.5, "pressure_drop_pa": 10.0},
        },
    )

    result = evaluate_mesh_independence(
        OpenFoamMeshIndependenceRequest(campaign_ids=CAMPAIGN_IDS), repository
    )

    assert result["status"] == "passed"
    assert result["mesh_independence_validated"] is True
    assert result["design_result_available"] is True
    assert result["recommended_profile"] == "fine"
    assert result["responses"]["t_max_c"] == 69.5
    assert result["comparisons"]["medium_to_fine"][
        "t_max_relative_change_percent"
    ] < 1.0
    assert result["comparisons"]["medium_to_fine"][
        "pressure_drop_relative_change_percent"
    ] < 5.0


def test_mesh_study_fails_closed_when_medium_to_fine_change_is_too_large(
    tmp_path,
):
    repository = ArtifactRepository(tmp_path)
    _save_campaigns(
        repository,
        {
            "coarse": {"t_max_c": 74.0, "pressure_drop_pa": 13.0},
            "medium": {"t_max_c": 70.0, "pressure_drop_pa": 10.2},
            "fine": {"t_max_c": 67.0, "pressure_drop_pa": 9.0},
        },
    )

    result = evaluate_mesh_independence(
        OpenFoamMeshIndependenceRequest(campaign_ids=CAMPAIGN_IDS), repository
    )

    assert result["status"] == "failed"
    assert result["mesh_independence_validated"] is False
    assert result["design_result_available"] is False
    assert result["responses"] is None


def test_mesh_study_rejects_unconverged_campaigns(tmp_path):
    repository = ArtifactRepository(tmp_path)
    _save_campaigns(
        repository,
        {
            profile: {"t_max_c": 70.0, "pressure_drop_pa": 10.0}
            for profile in CAMPAIGN_IDS
        },
        converged=False,
    )

    result = evaluate_mesh_independence(
        OpenFoamMeshIndependenceRequest(campaign_ids=CAMPAIGN_IDS), repository
    )

    assert result["campaigns_validated"] is False
    assert len(result["validation_errors"]) == 3
    assert result["results_available"] is False
