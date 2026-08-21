from app.domain.cae import OpenFoamSmokeRequest
from app.domain.models import DesignParameters
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam_smoke import run_openfoam_smoke


def test_smoke_reports_unavailable_environment_without_fake_results(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.openfoam_smoke.shutil.which", lambda _command: None)
    result = run_openfoam_smoke(
        OpenFoamSmokeRequest(
            design=DesignParameters(
                fin_count=20,
                fin_thickness=0.5,
                fin_height=30,
                fin_spacing=1.5,
                air_velocity=2,
            )
        ),
        ArtifactRepository(tmp_path),
    )

    assert result["status"] == "environment_unavailable"
    assert result["solver_executed"] is False
    assert result["solver_smoke_validated"] is False
    assert result["field_and_material_contract_validated"] is False
    assert result["results_available"] is False
    assert result["not_cfd_result"] is True
    assert result["missing_commands"]
