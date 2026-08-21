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
            "Allsolve",
            "0.orig/T",
            "0.orig/U",
            "system/blockMeshDict",
            "system/snappyHexMeshDict",
            "system/decomposeParDict",
            "system/fluid/decomposeParDict",
            "system/solid/decomposeParDict",
            "system/fluid/changeDictionaryDict",
            "system/solid/changeDictionaryDict",
            "constant/regionProperties",
            "constant/fluid/thermophysicalProperties",
            "constant/solid/thermophysicalProperties",
            "constant/solid/fvOptions",
            "constant/triSurface/heatsink-mm.stl",
        } <= names
        manifest = json.loads(archive.read("case.json"))
        assert manifest["not_cfd_result"] is True
        assert manifest["boundary_conditions"]["inlet_velocity_m_s"] == 2.8
        assert "closed fused" in manifest["geometry_contract"]
        assert manifest["mesh_strategy"]["target_cells_through_fin_thickness"] == 2
        assert manifest["mesh_profile"] == "medium"
        assert manifest["mesh_strategy"]["resolution_factor"] == 1
        assert manifest["mesh_strategy"]["per_region_quality_required"] is True
        assert manifest["field_contract"]["smoke_solve_only"] is True
        assert manifest["field_contract"]["production_solve_supported"] is True
        assert "solid Tmax" in manifest["field_contract"]["response_extraction"]
        allrun = archive.read("Allrun").decode()
        assert "surfaceCheck constant/triSurface/heatsink.stl" in allrun
        assert "checkMesh -allRegions" in allrun
        assert "chtMultiRegionFoam |" not in allrun
        assert "changeDictionary -region fluid" in allrun
        assert "changeDictionary -region solid" in allrun
        assert "chtMultiRegionFoam" in archive.read("Allsolve").decode()
        control = archive.read("system/controlDict").decode()
        assert "solidTemperature" in control
        assert "inletPressure" in control
        assert "outletPressure" in control
        assert "solidHeatRate" in control
        assert "numberOfSubdomains 2" in archive.read("system/decomposeParDict").decode()
        block_mesh = archive.read("system/blockMeshDict").decode()
        assert "(-0.030000 -0.010000 -0.005000)" in block_mesh
        assert "0.130000" in block_mesh
        snappy = archive.read("system/snappyHexMeshDict").decode()
        assert ") fluid)" in snappy
        assert ") solid)" in snappy


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


def test_mesh_profiles_are_distinct_traceable_case_fingerprints(tmp_path):
    repository = ArtifactRepository(tmp_path)
    design = DesignParameters(
        fin_count=20,
        fin_thickness=0.5,
        fin_height=30,
        fin_spacing=1.5,
        air_velocity=2.0,
    )

    coarse = prepare_openfoam_case(
        OpenFoamCaseRequest(design=design, mesh_profile="coarse"), repository
    )
    fine = prepare_openfoam_case(
        OpenFoamCaseRequest(design=design, mesh_profile="fine"), repository
    )

    assert coarse["case_id"] != fine["case_id"]
    with zipfile.ZipFile(
        repository.cae_artifact_path(coarse["case_id"], f'{coarse["case_id"]}.zip')
    ) as coarse_archive, zipfile.ZipFile(
        repository.cae_artifact_path(fine["case_id"], f'{fine["case_id"]}.zip')
    ) as fine_archive:
        coarse_manifest = json.loads(coarse_archive.read("case.json"))
        fine_manifest = json.loads(fine_archive.read("case.json"))
    assert coarse_manifest["mesh_strategy"]["resolution_factor"] == 0.8
    assert fine_manifest["mesh_strategy"]["resolution_factor"] == 1.25
    assert coarse_manifest["mesh_strategy"]["background_cells"]["y"] < fine_manifest[
        "mesh_strategy"
    ]["background_cells"]["y"]
