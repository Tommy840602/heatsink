from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_contract():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_predict_contract():
    response = client.post("/api/v1/simulations/predict", json={"fin_count": 48, "fin_thickness": 0.65, "fin_height": 52, "fin_spacing": 2.4, "air_velocity": 3.2})
    assert response.status_code == 200
    assert set(response.json()) >= {"t_max", "thermal_resistance", "pressure_drop", "mass"}


def test_invalid_design_returns_422():
    response = client.post("/api/v1/simulations/predict", json={"fin_count": 4, "fin_thickness": 0.65, "fin_height": 52, "fin_spacing": 2.4, "air_velocity": 3.2})
    assert response.status_code == 422


def test_cae_runtime_requirements_contract():
    response = client.get("/api/v1/cae/runtime-requirements")

    assert response.status_code == 200
    payload = response.json()
    meta = payload.pop("meta")
    assert meta["request_id"].startswith("req_")
    assert payload.pop("error") is None
    assert payload == {
        "target_distribution": "OpenCFD OpenFOAM v2312",
        "architecture": "linux/amd64",
        "queue": "thermoform-cae",
        "queue_tasks": ["cae", "cae_mesh", "cae_smoke", "cae_solve", "cae_campaign", "cae_mesh_study", "cae_benchmark"],
        "tutorial": "heatTransfer/chtMultiRegionFoam/multiRegionHeater",
        "worker_profile": "cae",
        "package_source": "https://dl.openfoam.com/repos/deb/",
        "result_policy": "A runtime benchmark never becomes a heat-sink CFD result.",
        "mesh_policy": "A design mesh must pass watertight geometry, region-interface, and per-region quality gates before thermal fields are enabled.",
        "smoke_policy": "A one-step CHT run validates fields, materials, heat source, and solver startup only; it never becomes a design response.",
        "response_policy": "Responses require at least five stable samples, residual convergence, energy balance, and a non-smoke result mode.",
        "solve_policy": "Production CHT runs use immutable checkpoints, may resume only the same case fingerprint, and publish responses only after every numerical gate passes.",
        "campaign_policy": "Campaigns chain production checkpoints until convergence, cancellation, target time, segment limit, or runtime budget; cancellation is cooperative at checkpoint boundaries.",
        "mesh_independence_policy": "A publishable design result requires converged coarse, medium, and fine campaigns plus medium-to-fine Tmax and pressure-drop changes within configured limits.",
    }
