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
