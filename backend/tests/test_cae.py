import json
import zipfile

from app.domain.cae import OpenFoamCaseRequest
from app.domain.models import DesignParameters
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam import prepare_openfoam_case


def test_openfoam_case_is_packaged_without_claiming_cfd_results(tmp_path):
    repository = ArtifactRepository(tmp_path)
    result = prepare_openfoam_case(
        OpenFoamCaseRequest(
            design=DesignParameters(
                fin_count=36,
                fin_thickness=0.6,
                fin_height=44,
                fin_spacing=2.2,
                air_velocity=2.8,
            )
        ),
        repository,
    )

    assert result["case_generated"] is True
    assert result["case_validated"] is False
    assert result["solver_executed"] is False
    assert result["results_available"] is False
    assert result["not_cfd_result"] is True
    assert result["result_type"] is None

    package = repository.cae_artifact_path(result["case_id"], f'{result["case_id"]}.zip')
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert {
            "README.md",
            "case.json",
            "Allrun",
            "system/blockMeshDict",
            "system/snappyHexMeshDict",
            "constant/triSurface/heatsink-mm.stl",
        } <= names
        manifest = json.loads(archive.read("case.json"))
        assert manifest["not_cfd_result"] is True
        assert manifest["boundary_conditions"]["inlet_velocity_m_s"] == 2.8


def test_openfoam_request_reports_missing_solver_instead_of_fabricating_output(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.openfoam.shutil.which", lambda _command: None)
    result = prepare_openfoam_case(
        OpenFoamCaseRequest(
            design=DesignParameters(
                fin_count=30,
                fin_thickness=0.5,
                fin_height=40,
                fin_spacing=2.0,
                air_velocity=2.0,
            ),
            run_solver=True,
        ),
        ArtifactRepository(tmp_path),
    )
    assert result["solver_status"] == "solver_unavailable"
    assert result["solver_executed"] is False
    assert result["results_available"] is False
