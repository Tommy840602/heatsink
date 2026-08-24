from app.domain.agent import EngineeringAgentRequest
from app.repositories.artifacts import ArtifactRepository
from app.services import engineering_agent


def test_agent_exposes_complete_bounded_toolchain(tmp_path, monkeypatch):
    recommendation = {
        "design": {
            "fin_count": 44,
            "fin_thickness": 0.6,
            "fin_height": 50.0,
            "fin_spacing": 2.2,
            "air_velocity": 2.8,
        },
        "responses": {"t_max": 72.0, "thermal_resistance": 0.47, "pressure_drop": 18.0, "mass": 280.0},
    }
    monkeypatch.setattr(
        engineering_agent,
        "run_phase1",
        lambda *_args, **_kwargs: {
            "workflow_id": "workflow_test",
            "dataset_version": "dataset_test",
            "model_id": "model_test",
            "experiment_count": 48,
            "selected_models": {"t_max": "GPR"},
            "model_metrics": {"t_max": [{"model": "GPR", "cv_rmse": 1.0}]},
            "optimization": {"recommended": recommendation, "pareto": [recommendation]},
        },
    )
    monkeypatch.setattr(
        engineering_agent,
        "generate_cad",
        lambda *_args, **_kwargs: {
            "cad_id": "cad_test",
            "step_generated": True,
            "downloads": {"step": "/api/v1/cad/cad_test/artifacts/cad_test.step"},
        },
    )

    result = engineering_agent.execute_engineering_agent(
        EngineeringAgentRequest(
            instruction="找出 Tmax < 75°C、Mass < 300 g，且壓降最低的設計，並產生 CAD"
        ),
        ArtifactRepository(tmp_path),
    )

    tools = {entry["tool"] for entry in result["tool_results"]}
    assert tools == {
        "run_doe",
        "run_simulation",
        "train_surrogate",
        "evaluate_models",
        "optimize_design",
        "compare_designs",
        "generate_cad",
    }
    assert result["recommendation"]["cad"]["step_generated"] is True
    assert result["traceability"]["arbitrary_code_execution"] is False
    assert result["traceability"]["interpreted_constraints"] == {
        "t_max_limit": 75.0,
        "pressure_drop_limit": 35.0,
        "mass_limit": 300.0,
    }
    assert (tmp_path / "agent" / result["agent_run_id"] / "run.json").exists()
