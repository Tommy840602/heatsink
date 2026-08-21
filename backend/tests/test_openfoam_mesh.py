import zipfile

import pytest

from app.domain.cae import OpenFoamMeshRequest
from app.domain.models import DesignParameters
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam_mesh import _extract_case_package, run_openfoam_mesh


def test_design_mesh_reports_unavailable_environment_without_fake_results(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.services.openfoam_mesh.shutil.which", lambda _command: None)
    result = run_openfoam_mesh(
        OpenFoamMeshRequest(
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
    assert result["mesh_executed"] is False
    assert result["mesh_validated"] is False
    assert result["results_available"] is False
    assert result["not_cfd_result"] is True
    assert result["missing_commands"]
    assert ArtifactRepository(tmp_path).cae_artifact_path(
        result["mesh_run_id"], "mesh-report.json"
    ).exists()


def test_case_package_extraction_rejects_path_traversal(tmp_path):
    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../outside", "unsafe")

    destination = tmp_path / "case"
    destination.mkdir()
    with pytest.raises(ValueError, match="unsafe path"):
        _extract_case_package(package, destination)

    assert not (tmp_path / "outside").exists()
