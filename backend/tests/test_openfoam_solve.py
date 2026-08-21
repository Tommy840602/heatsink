import json
import zipfile

import pytest
from pydantic import ValidationError

from app.domain.cae import OpenFoamSolveRequest
from app.domain.models import DesignParameters
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam_solve import (
    CHECKPOINT_METADATA,
    _processor_latest_time,
    _safe_extract_checkpoint,
    _write_checkpoint,
    configure_production_case,
    run_openfoam_solve,
)


def _design() -> DesignParameters:
    return DesignParameters(
        fin_count=20,
        fin_thickness=0.5,
        fin_height=30,
        fin_spacing=1.5,
        air_velocity=2,
    )


def _request(**overrides) -> OpenFoamSolveRequest:
    return OpenFoamSolveRequest(design=_design(), **overrides)


def test_production_request_rejects_target_shorter_than_one_step():
    with pytest.raises(ValidationError):
        _request(target_end_time_s=0.000001, delta_t_s=0.00001)


def test_production_configuration_uses_latest_time_and_parallel_count(tmp_path):
    system = tmp_path / "system"
    system.mkdir()
    (system / "controlDict").write_text(
        "startFrom startTime;\nendTime 0.00001;\ndeltaT 0.00001;\n"
        "writeInterval 1;\npurgeWrite 1;\n",
        encoding="utf-8",
    )
    (system / "decomposeParDict").write_text("old", encoding="utf-8")

    configure_production_case(
        tmp_path,
        _request(
            target_end_time_s=0.002,
            delta_t_s=0.00002,
            write_interval_steps=5,
            parallel_processes=4,
        ),
    )

    control = (system / "controlDict").read_text(encoding="utf-8")
    assert "startFrom latestTime;" in control
    assert "endTime 0.002;" in control
    assert "deltaT 2e-05;" in control
    assert "writeInterval 5;" in control
    assert "purgeWrite 5;" in control
    assert "numberOfSubdomains 4;" in (system / "decomposeParDict").read_text(
        encoding="utf-8"
    )
    assert "numberOfSubdomains 4;" in (
        system / "fluid" / "decomposeParDict"
    ).read_text(encoding="utf-8")
    assert "numberOfSubdomains 4;" in (
        system / "solid" / "decomposeParDict"
    ).read_text(encoding="utf-8")
    assert "singleProcessorFaceSets" in (
        system / "fluid" / "decomposeParDict"
    ).read_text(encoding="utf-8")
    assert "patches (fluid_to_solid);" in (
        system / "fluid" / "topoSetDict"
    ).read_text(encoding="utf-8")
    assert "patches (solid_to_fluid);" in (
        system / "solid" / "topoSetDict"
    ).read_text(encoding="utf-8")


def test_checkpoint_round_trip_and_case_fingerprint_guard(tmp_path):
    case = tmp_path / "case"
    (case / "constant" / "fluid").mkdir(parents=True)
    (case / "system").mkdir()
    (case / "0.5" / "fluid").mkdir(parents=True)
    (case / "constant" / "fluid" / "thermophysicalProperties").write_text("air")
    (case / "system" / "controlDict").write_text("control")
    (case / "0.5" / "fluid" / "T").write_text("temperature")
    (case / "case.json").write_text("{}")
    metadata = {
        "case_id": "cae_abc123",
        "latest_time_s": 0.5,
        "mesh_validation": {"acceptance_passed": True},
    }
    checkpoint = tmp_path / "checkpoint.zip"

    _write_checkpoint(case, checkpoint, metadata)

    with zipfile.ZipFile(checkpoint) as archive:
        assert CHECKPOINT_METADATA in archive.namelist()
        assert "0.5/fluid/T" in archive.namelist()
    restored = tmp_path / "restored"
    restored.mkdir()
    assert _safe_extract_checkpoint(checkpoint, restored, "cae_abc123")["latest_time_s"] == 0.5
    assert (restored / "0.5" / "fluid" / "T").read_text() == "temperature"
    rejected = tmp_path / "rejected"
    rejected.mkdir()
    with pytest.raises(ValueError, match="different case fingerprint"):
        _safe_extract_checkpoint(checkpoint, rejected, "cae_different")


def test_parallel_checkpoint_uses_latest_processor_time(tmp_path):
    (tmp_path / "processor0" / "0").mkdir(parents=True)
    (tmp_path / "processor0" / "2e-05").mkdir()
    (tmp_path / "processor1" / "2e-05").mkdir(parents=True)

    assert _processor_latest_time(tmp_path) == 0.00002


def test_production_solve_fails_closed_when_worker_environment_is_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.services.openfoam_solve.shutil.which", lambda _command: None)
    repository = ArtifactRepository(tmp_path)

    result = run_openfoam_solve(_request(), repository)

    assert result["status"] == "environment_unavailable"
    assert result["results_available"] is False
    assert result["not_cfd_result"] is True
    assert result["checkpoint_created"] is False
    assert result["workspace_recovered"] is False
    assert result["missing_commands"]
    assert not (tmp_path / "cae-work" / result["solve_run_id"]).exists()
    report = repository.cae_artifact_path(
        result["solve_run_id"], "solve-report.json"
    )
    assert json.loads(report.read_text())["results_available"] is False
