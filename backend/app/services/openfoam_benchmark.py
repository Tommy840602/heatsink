import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.cae import OpenFoamBenchmarkRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_validation import validate_cae_run


OPENFOAM_TARGET = "OpenCFD OpenFOAM v2312"
TUTORIAL_RELATIVE_PATH = Path("heatTransfer/chtMultiRegionFoam/multiRegionHeater")


def _tutorial_path() -> Path | None:
    explicit = os.getenv("THERMOFORM_OPENFOAM_BENCHMARK_CASE")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.is_dir() else None
    tutorials = os.getenv("FOAM_TUTORIALS")
    if not tutorials:
        return None
    path = (Path(tutorials).expanduser().resolve() / TUTORIAL_RELATIVE_PATH)
    return path if path.is_dir() else None


def _collect_logs(case_root: Path, process_output: str) -> tuple[str, str]:
    mesh_parts = [process_output]
    solver_parts = [process_output]
    for path in sorted(case_root.rglob("log.*")):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "mesh" in path.name.lower() or "check" in path.name.lower():
            mesh_parts.append(content)
        solver_parts.append(content)
    return "\n".join(mesh_parts), "\n".join(solver_parts)


def run_openfoam_benchmark(
    request: OpenFoamBenchmarkRequest,
    repository: ArtifactRepository | None = None,
) -> dict[str, Any]:
    repository = repository or ArtifactRepository()
    fingerprint = {
        "tutorial": request.tutorial,
        "target": OPENFOAM_TARGET,
        "criteria": request.criteria.model_dump(),
    }
    benchmark_id = repository.version(fingerprint, "benchmark")
    source = _tutorial_path()
    required = ["foamVersion", "blockMesh", "checkMesh", "chtMultiRegionFoam"]
    missing_commands = [command for command in required if shutil.which(command) is None]

    if source is None or missing_commands:
        validation = validate_cae_run("", "", request.criteria)
        result = {
            "benchmark_id": benchmark_id,
            "status": "environment_unavailable",
            "target_distribution": OPENFOAM_TARGET,
            "tutorial": request.tutorial,
            "tutorial_found": source is not None,
            "missing_commands": missing_commands,
            "openfoam_version": None,
            "solver_executed": False,
            "benchmark_validated": False,
            "results_available": False,
            "not_design_cfd_result": True,
            "validation": validation,
            "generated_at": datetime.now(UTC).isoformat(),
            "downloads": {"report": f"/api/v1/cae/{benchmark_id}/artifacts/report.json", "log": None},
            "notice": "The OpenFOAM benchmark was not executed. Install/source the target distribution and provide its official multiRegionHeater tutorial path.",
        }
        repository.save_cae_artifact(benchmark_id, "report.json", json.dumps(result, indent=2, sort_keys=True))
        return result

    version_result = subprocess.run(
        ["foamVersion"], capture_output=True, text=True, check=False, timeout=30
    )
    openfoam_version = (version_result.stdout + version_result.stderr).strip()
    if version_result.returncode != 0 or "2312" not in openfoam_version:
        validation = validate_cae_run("", "", request.criteria)
        result = {
            "benchmark_id": benchmark_id,
            "status": "version_mismatch",
            "target_distribution": OPENFOAM_TARGET,
            "openfoam_version": openfoam_version or None,
            "tutorial": request.tutorial,
            "tutorial_found": True,
            "missing_commands": [],
            "solver_executed": False,
            "benchmark_validated": False,
            "results_available": False,
            "not_design_cfd_result": True,
            "validation": validation,
            "generated_at": datetime.now(UTC).isoformat(),
            "downloads": {"report": f"/api/v1/cae/{benchmark_id}/artifacts/report.json", "log": None},
            "notice": "The sourced OpenFOAM distribution does not match the pinned OpenCFD v2312 benchmark target.",
        }
        repository.save_cae_artifact(benchmark_id, "report.json", json.dumps(result, indent=2, sort_keys=True))
        return result

    with tempfile.TemporaryDirectory(prefix="thermoform-benchmark-") as temporary:
        case_root = Path(temporary) / request.tutorial
        shutil.copytree(source, case_root)
        allrun = case_root / "Allrun"
        if not allrun.exists():
            raise FileNotFoundError(f"Official tutorial Allrun not found under {source}")
        try:
            completed = subprocess.run(
                ["bash", str(allrun)],
                cwd=case_root,
                capture_output=True,
                text=True,
                timeout=request.max_runtime_seconds,
                check=False,
            )
            process_output = completed.stdout + "\n" + completed.stderr
            execution_status = "completed" if completed.returncode == 0 else "failed"
            if completed.returncode == 0:
                mesh_check = subprocess.run(
                    ["checkMesh", "-allRegions", "-allGeometry", "-allTopology"],
                    cwd=case_root,
                    capture_output=True,
                    text=True,
                    timeout=min(request.max_runtime_seconds, 600),
                    check=False,
                )
                process_output += "\n" + mesh_check.stdout + "\n" + mesh_check.stderr
                if mesh_check.returncode != 0:
                    execution_status = "failed"
        except subprocess.TimeoutExpired as exc:
            process_output = (exc.stdout or "") + "\n" + (exc.stderr or "")
            execution_status = "timed_out"
        mesh_log, solver_log = _collect_logs(case_root, process_output)

    validation = validate_cae_run(mesh_log, solver_log, request.criteria)
    benchmark_validated = bool(
        execution_status == "completed"
        and validation["gates"]["mesh_quality"]["passed"]
        and validation["gates"]["convergence"]["passed"]
    )
    log_name = "benchmark.log"
    repository.save_cae_artifact(benchmark_id, log_name, solver_log[-500000:])
    result = {
        "benchmark_id": benchmark_id,
        "status": "passed" if benchmark_validated else "validation_failed",
        "target_distribution": OPENFOAM_TARGET,
        "openfoam_version": openfoam_version,
        "tutorial": request.tutorial,
        "tutorial_found": True,
        "missing_commands": [],
        "solver_executed": True,
        "execution_status": execution_status,
        "benchmark_validated": benchmark_validated,
        "results_available": False,
        "not_design_cfd_result": True,
        "validation": validation,
        "generated_at": datetime.now(UTC).isoformat(),
        "downloads": {
            "report": f"/api/v1/cae/{benchmark_id}/artifacts/report.json",
            "log": f"/api/v1/cae/{benchmark_id}/artifacts/{log_name}",
        },
        "notice": "This validates the official OpenFOAM tutorial environment and numerical completion only. Energy balance and design response gates remain mandatory for a heat-sink result.",
    }
    repository.save_cae_artifact(benchmark_id, "report.json", json.dumps(result, indent=2, sort_keys=True))
    return result
