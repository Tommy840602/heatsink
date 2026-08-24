from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db.session import Base, get_db
from app.main import app
from app.services.metadata import _json_safe


def test_postgres_json_metadata_is_strictly_finite():
    assert _json_safe({"missing": float("nan"), "infinite": float("inf")}) == {
        "missing": None,
        "infinite": None,
    }


def test_project_and_versioned_design_crud_contract(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'metadata.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def session_override():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = session_override
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/projects",
                json={"name": "CPU Heat Sink", "description": "DOE workspace"},
            )
            assert created.status_code == 201
            project = created.json()["data"]
            assert set(project["design_space"]) == {
                "fin_count", "fin_thickness", "fin_height", "fin_spacing", "air_velocity"
            }
            assert created.json()["meta"]["request_id"].startswith("req_")
            assert created.headers["X-Request-ID"] == created.json()["meta"]["request_id"]

            payload = {
                "name": "Primary design space",
                "parameters": {
                    "fin_count": 48,
                    "fin_thickness": 0.65,
                    "fin_height": 52,
                    "fin_spacing": 2.4,
                    "air_velocity": 3.2,
                },
            }
            first = client.post(f"/api/v1/projects/{project['id']}/designs", json=payload)
            second = client.post(f"/api/v1/projects/{project['id']}/designs", json=payload)
            assert first.status_code == second.status_code == 201
            assert first.json()["data"]["version"] == 1
            assert second.json()["data"]["version"] == 2

            alias = client.post(
                "/api/v1/designs",
                json={"project_id": project["id"], **payload},
            )
            assert alias.status_code == 201
            assert alias.json()["data"]["version"] == 3

            designs = client.get(f"/api/v1/projects/{project['id']}/designs")
            assert designs.status_code == 200
            assert len(designs.json()["data"]) == 3

            archived = client.delete(f"/api/v1/projects/{project['id']}")
            assert archived.json()["data"]["status"] == "archived"
            assert archived.json()["meta"]["status"] == "archived"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
