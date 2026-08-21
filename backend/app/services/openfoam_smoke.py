import json
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.cae import OpenFoamCaseRequest, OpenFoamSmokeRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_validation import (
    extract_provisional_responses,
    validate_region_mesh,
    validate_solver_smoke,
    validate_response_readiness,
)
from app.services.openfoam import mesh_required_commands, prepare_openfoam_case
from app.services.openfoam_mesh import _extract_case_package, _process_output


SMOKE_CONTRACT_VERSION = "cht-smoke-v2"


def run_openfoam_smoke(
    request: OpenFoamSmokeRequest,
    repository: ArtifactRepository | None = None,
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    case = prepare_openfoam_case(
        OpenFoamCaseRequest(
            design=request.design,
            mesh_profile=request.mesh_profile,
            heat_load_w=request.heat_load_w,
            ambient_temperature_c=request.ambient_temperature_c,
            run_solver=False,
        ),
        repository,
    )
    case_id = case["case_id"]
    smoke_id = repository.version(
        {
            "case_id": case_id,
            "criteria": request.criteria.model_dump(),
            "mode": "one-step",
            "contract": SMOKE_CONTRACT_VERSION,
        },
        "smoke",
    )
    required = [*mesh_required_commands(), "chtMultiRegionFoam"]
    missing_commands = [command for command in required if shutil.which(command) is None]
    execution_status = "environment_unavailable"
    mesh_log = ""
    solver_log = ""

    if not missing_commands:
        package = repository.cae_artifact_path(case_id, f"{case_id}.zip")
        with tempfile.TemporaryDirectory(prefix="thermoform-cht-smoke-") as temporary:
            case_root = Path(temporary) / case_id
            case_root.mkdir()
            _extract_case_package(package, case_root)
            allrun = case_root / "Allrun"
            allsolve = case_root / "Allsolve"
            allrun.chmod(0o755)
            allsolve.chmod(0o755)
            started = time.monotonic()
            try:
                preprocessing = subprocess.run(
                    [str(allrun)],
                    cwd=case_root,
                    capture_output=True,
                    text=True,
                    timeout=request.max_runtime_seconds,
                    check=False,
                )
                mesh_log = _process_output(preprocessing.stdout, preprocessing.stderr)
                mesh_validation = validate_region_mesh(mesh_log, request.criteria)
                if preprocessing.returncode != 0:
                    execution_status = "preprocessing_failed"
                elif not mesh_validation["acceptance_passed"]:
                    execution_status = "mesh_validation_failed"
                else:
                    remaining = request.max_runtime_seconds - (time.monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(str(allsolve), request.max_runtime_seconds)
                    solve = subprocess.run(
                        [str(allsolve)],
                        cwd=case_root,
                        capture_output=True,
                        text=True,
                        timeout=remaining,
                        check=False,
                    )
                    solver_log = _process_output(solve.stdout, solve.stderr)
                    execution_status = "completed" if solve.returncode == 0 else "solver_failed"
            except subprocess.TimeoutExpired as exc:
                partial = _process_output(exc.stdout, exc.stderr)
                if mesh_log:
                    solver_log = partial
                else:
                    mesh_log = partial
                execution_status = "timed_out"
            except OSError as exc:
                solver_log = str(exc)
                execution_status = "failed"

    mesh_validation = validate_region_mesh(mesh_log, request.criteria)
    smoke_validation = validate_solver_smoke(solver_log)
    provisional_responses = extract_provisional_responses(
        solver_log, request.heat_load_w, request.ambient_temperature_c
    )
    response_readiness = validate_response_readiness(
        solver_log,
        request.heat_load_w,
        request.ambient_temperature_c,
        request.criteria,
        allow_results=False,
    )
    smoke_passed = bool(
        execution_status == "completed"
        and mesh_validation["acceptance_passed"]
        and smoke_validation["passed"]
    )
    combined_log = mesh_log + "\n--- CHT SMOKE SOLVE ---\n" + solver_log
    log_name = "smoke.log"
    report_name = "smoke-report.json"
    if combined_log.strip("\n-"):
        repository.save_cae_artifact(smoke_id, log_name, combined_log[-2_000_000:])
    result = {
        "smoke_id": smoke_id,
        "case_id": case_id,
        "mesh_profile": request.mesh_profile,
        "contract_version": SMOKE_CONTRACT_VERSION,
        "status": (
            "passed"
            if smoke_passed
            else "validation_failed"
            if execution_status == "completed"
            else execution_status
        ),
        "execution_status": execution_status,
        "missing_commands": missing_commands,
        "solver_executed": bool(solver_log),
        "solver_smoke_validated": smoke_passed,
        "field_and_material_contract_validated": smoke_passed,
        "results_available": False,
        "not_cfd_result": True,
        "mesh_validation": mesh_validation,
        "smoke_validation": smoke_validation,
        "provisional_responses": provisional_responses,
        "response_readiness": response_readiness,
        "generated_at": datetime.now(UTC).isoformat(),
        "downloads": {
            "case_package": case["downloads"]["case_package"],
            "report": f"/api/v1/cae/{smoke_id}/artifacts/{report_name}",
            "log": f"/api/v1/cae/{smoke_id}/artifacts/{log_name}",
        },
        "notice": (
            "The one-step CHT smoke solve initialized both regions and solved coupled momentum/enthalpy fields. "
            "It is not a converged CFD result and exposes no design responses."
            if smoke_passed
            else "The heat-sink CHT smoke contract did not pass. No CFD result is available."
        ),
    }
    repository.save_cae_artifact(
        smoke_id, report_name, json.dumps(result, indent=2, sort_keys=True)
    )
    return result
