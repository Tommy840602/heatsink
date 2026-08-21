import json
import shutil
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.cae import OpenFoamCaseRequest, OpenFoamMeshRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_validation import validate_region_mesh
from app.services.openfoam import mesh_required_commands, prepare_openfoam_case


def _process_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    def decode(value: str | bytes | None) -> str:
        return value.decode(errors="replace") if isinstance(value, bytes) else value or ""

    return decode(stdout) + "\n" + decode(stderr)


def _extract_case_package(package: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    with zipfile.ZipFile(package) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination_root):
                raise ValueError("OpenFOAM case package contains an unsafe path")
        archive.extractall(destination)


def run_openfoam_mesh(
    request: OpenFoamMeshRequest,
    repository: ArtifactRepository | None = None,
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    case = prepare_openfoam_case(
        OpenFoamCaseRequest(design=request.design, run_solver=False), repository
    )
    case_id = case["case_id"]
    mesh_run_id = repository.version(
        {"case_id": case_id, "criteria": request.criteria.model_dump()}, "mesh"
    )
    missing_commands = [
        command for command in mesh_required_commands() if shutil.which(command) is None
    ]
    execution_status = "environment_unavailable"
    process_output = ""

    if not missing_commands:
        package = repository.cae_artifact_path(case_id, f"{case_id}.zip")
        with tempfile.TemporaryDirectory(prefix="thermoform-design-mesh-") as temporary:
            case_root = Path(temporary) / case_id
            case_root.mkdir()
            _extract_case_package(package, case_root)
            allrun = case_root / "Allrun"
            allrun.chmod(0o755)
            try:
                completed = subprocess.run(
                    [str(allrun)],
                    cwd=case_root,
                    capture_output=True,
                    text=True,
                    timeout=request.max_runtime_seconds,
                    check=False,
                )
                process_output = _process_output(completed.stdout, completed.stderr)
                execution_status = "completed" if completed.returncode == 0 else "failed"
            except subprocess.TimeoutExpired as exc:
                process_output = _process_output(exc.stdout, exc.stderr)
                execution_status = "timed_out"
            except OSError as exc:
                process_output = str(exc)
                execution_status = "failed"

    validation = validate_region_mesh(process_output, request.criteria)
    mesh_validated = bool(
        execution_status == "completed" and validation["acceptance_passed"]
    )
    log_name = "mesh.log"
    report_name = "mesh-report.json"
    if process_output:
        repository.save_cae_artifact(mesh_run_id, log_name, process_output[-2_000_000:])
    result = {
        "mesh_run_id": mesh_run_id,
        "case_id": case_id,
        "status": (
            "passed"
            if mesh_validated
            else "validation_failed"
            if execution_status == "completed"
            else execution_status
        ),
        "execution_status": execution_status,
        "missing_commands": missing_commands,
        "mesh_executed": execution_status in {"completed", "failed", "timed_out"},
        "mesh_validated": mesh_validated,
        "results_available": False,
        "not_cfd_result": True,
        "validation": validation,
        "generated_at": datetime.now(UTC).isoformat(),
        "downloads": {
            "case_package": case["downloads"]["case_package"],
            "report": f"/api/v1/cae/{mesh_run_id}/artifacts/{report_name}",
            "log": (
                f"/api/v1/cae/{mesh_run_id}/artifacts/{log_name}"
                if process_output
                else None
            ),
        },
        "notice": (
            "The watertight heat-sink geometry and both region meshes passed the configured preprocessing gates. "
            "This is not a thermal CFD result; fields, materials, convergence, energy balance, and responses remain required."
            if mesh_validated
            else "The design mesh did not pass every configured preprocessing gate. No thermal CFD result is available."
        ),
    }
    repository.save_cae_artifact(
        mesh_run_id, report_name, json.dumps(result, indent=2, sort_keys=True)
    )
    return result
