from app.domain.models import DesignParameters
from app.domain.phase1 import Phase1WorkflowRequest
from app.domain.phase2 import (
    BayesianProposalRequest,
    CadGenerationRequest,
    Phase2WorkflowRequest,
)
from app.repositories.artifacts import ArtifactRepository
from app.services.bayesian import propose
from app.services.cad import generate_cad
from app.services.phase2_workflow import run_phase2
from app.services.workflow import run_phase1


def phase1_artifacts(repository):
    return run_phase1(
        Phase1WorkflowRequest(
            method="LHS",
            runs=30,
            seed=17,
            optimization_generations=10,
        ),
        repository,
    )


def test_bayesian_acquisitions_return_bounded_feasible_proposals(tmp_path):
    repository = ArtifactRepository(tmp_path)
    phase1 = phase1_artifacts(repository)
    for acquisition in ("EI", "PI", "UCB"):
        result = propose(
            BayesianProposalRequest(
                model_id=phase1["model_id"],
                dataset_version=phase1["dataset_version"],
                acquisition=acquisition,
                candidate_pool_size=256,
                seed=4,
            ),
            repository,
        )
        candidate = result["proposals"][0]
        DesignParameters(**candidate["design"])
        assert candidate["objective_uncertainty"] >= 0
        assert result["acquisition"] == acquisition


def test_phase2_updates_dataset_retrains_and_generates_cad_artifacts(tmp_path):
    repository = ArtifactRepository(tmp_path)
    phase1 = phase1_artifacts(repository)
    result = run_phase2(
        Phase2WorkflowRequest(
            model_id=phase1["model_id"],
            dataset_version=phase1["dataset_version"],
            acquisition="EI",
            iterations=1,
            seed=23,
        ),
        repository,
    )

    assert result["status"] == "completed"
    assert result["experiment_count"] == phase1["experiment_count"] + 1
    assert result["dataset_version"] != phase1["dataset_version"]
    assert result["proposals"][0]["simulator_version"] == "1.0.0"
    assert result["cad"]["stl_generated"] is True
    assert result["cad"]["not_cfd_or_cae"] is True
    assert abs(result["cad"]["cad_mass_estimate_g"] - result["best_response"]["mass"]) < 0.02
    assert repository.cad_artifact_path(
        result["cad"]["cad_id"], f'{result["cad"]["cad_id"]}.py'
    ).exists()
    assert repository.cad_artifact_path(
        result["cad"]["cad_id"], f'{result["cad"]["cad_id"]}.stl'
    ).exists()


def test_cad_rejects_an_explicit_base_that_cannot_fit_the_fins(tmp_path):
    repository = ArtifactRepository(tmp_path)
    request = CadGenerationRequest(
        design=DesignParameters(
            fin_count=60,
            fin_thickness=1.0,
            fin_height=60,
            fin_spacing=4.0,
            air_velocity=3.0,
        ),
        base_width=120,
    )
    try:
        generate_cad(request, repository)
    except ValueError as exc:
        assert "do not fit" in str(exc)
    else:
        raise AssertionError("invalid CAD packing should fail")
