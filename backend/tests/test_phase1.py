from app.domain.models import DesignParameters, DoeRequest
from app.domain.phase1 import Phase1WorkflowRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.analysis import analyze
from app.services.doe import generate_doe
from app.services.simulator import simulate
from app.services.surrogates import predict_design
from app.services.workflow import run_phase1


def simulation_records(runs: int = 30):
    _, matrix = generate_doe(DoeRequest(method="LHS", runs=runs, seed=9))
    return [
        {**row, **simulate(DesignParameters(**row), seed=index).model_dump()}
        for index, row in enumerate(matrix)
    ]


def test_analysis_returns_rsm_anova_and_diagnostics():
    result = analyze(simulation_records(), "t_max")
    assert result["response"] == "t_max"
    assert result["anova"][0]["source"] == "Model"
    assert len(result["main_effects"]) == 5
    assert len(result["interactions"]) == 10
    assert len(result["diagnostics"]["residual_vs_fitted"]) == 30


def test_phase1_workflow_persists_traceable_model_and_optimizes(tmp_path):
    repository = ArtifactRepository(tmp_path)
    result = run_phase1(
        Phase1WorkflowRequest(
            method="LHS",
            runs=30,
            seed=11,
            optimization_generations=10,
        ),
        repository,
    )

    assert result["status"] == "completed"
    assert result["experiment_count"] == 30
    assert set(result["selected_models"]) == {
        "t_max",
        "thermal_resistance",
        "pressure_drop",
        "mass",
    }
    assert result["optimization"]["recommended"] is not None
    assert result["traceability"]["physics_result_is_cfd"] is False
    assert (tmp_path / "experiments" / f'{result["dataset_version"]}.parquet').exists()
    assert (tmp_path / "experiments" / f'{result["dataset_version"]}.metadata.json').exists()
    model_metadata = tmp_path / "models" / result["model_id"] / "metadata.json"
    assert "NaN" not in model_metadata.read_text(encoding="utf-8")

    bundle = repository.load_model(result["model_id"])
    prediction = predict_design(
        bundle,
        {
            "fin_count": 40,
            "fin_thickness": 0.6,
            "fin_height": 40.0,
            "fin_spacing": 2.5,
            "air_velocity": 2.5,
        },
    )
    assert prediction["t_max"] > 25.0
    assert prediction["t_max_uncertainty"] >= 0.0
