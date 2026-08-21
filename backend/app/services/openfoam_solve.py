import json
import os
import re
import shutil
import signal
import subprocess
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.cae import OpenFoamCaseRequest, OpenFoamSolveRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.cae_validation import validate_region_mesh, validate_response_readiness
from app.services.openfoam import mesh_required_commands, prepare_openfoam_case
from app.services.openfoam_mesh import _extract_case_package, _process_output


SOLVE_CONTRACT_VERSION = "cht-production-v1"
CHECKPOINT_FILENAME = "checkpoint.zip"
CHECKPOINT_METADATA = "thermoform-checkpoint.json"


def _replace_dictionary_value(text: str, key: str, value: str) -> str:
    updated, count = re.subn(
        rf"(?m)^(\s*{re.escape(key)}\s+)[^;]+;",
        rf"\g<1>{value};",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"OpenFOAM controlDict is missing {key}")
    return updated


def configure_production_case(case_root: Path, request: OpenFoamSolveRequest) -> None:
    control_path = case_root / "system" / "controlDict"
    control = control_path.read_text(encoding="utf-8")
    values = {
        "startFrom": "latestTime",
        "endTime": f"{request.target_end_time_s:.12g}",
        "deltaT": f"{request.delta_t_s:.12g}",
        "writeInterval": str(request.write_interval_steps),
        "purgeWrite": "5",
    }
    for key, value in values.items():
        control = _replace_dictionary_value(control, key, value)
    control_path.write_text(control, encoding="utf-8")
    root_decomposition = (
        "FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\n"
        f"numberOfSubdomains {request.parallel_processes};\n"
        "method scotch;\n"
    )
    (case_root / "system" / "decomposeParDict").write_text(
        root_decomposition, encoding="utf-8"
    )
    for region, patch in (
        ("fluid", "fluid_to_solid"),
        ("solid", "solid_to_fluid"),
    ):
        directory = case_root / "system" / region
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "decomposeParDict").write_text(
            root_decomposition
            + "constraints\n{\n"
            + "  coupledInterface\n  {\n"
            + "    type singleProcessorFaceSets;\n"
            + "    sets ((thermoformCoupledFaces 0));\n"
            + "    enabled true;\n"
            + "  }\n}\n",
            encoding="utf-8",
        )
        (directory / "topoSetDict").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object topoSetDict; }\n"
            "actions\n(\n  {\n"
            "    name thermoformCoupledFaces;\n"
            "    type faceSet;\n"
            "    action new;\n"
            "    source patchToFace;\n"
            f"    patches ({patch});\n"
            "  }\n);\n",
            encoding="utf-8",
        )


def _run_process(
    command: list[str], cwd: Path, timeout_seconds: float
) -> tuple[int | None, str, bool]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env={
            **os.environ,
            "OMPI_ALLOW_RUN_AS_ROOT": "1",
            "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1",
        },
    )
    try:
        stdout, stderr = process.communicate(timeout=max(timeout_seconds, 1))
        return process.returncode, _process_output(stdout, stderr), False
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        partial = _process_output(exc.stdout, exc.stderr)
        completed = _process_output(stdout, stderr)
        if completed and completed not in partial:
            partial += completed
        return None, partial, True


def _latest_time(case_root: Path) -> float | None:
    times: list[float] = []
    for child in case_root.iterdir():
        if not child.is_dir():
            continue
        try:
            times.append(float(child.name))
        except ValueError:
            continue
    return max(times, default=None)


def _processor_latest_time(case_root: Path) -> float | None:
    processor_zero = case_root / "processor0"
    return _latest_time(processor_zero) if processor_zero.is_dir() else None


def _safe_extract_checkpoint(
    checkpoint: Path, destination: Path, expected_case_id: str
) -> dict[str, Any]:
    destination_root = destination.resolve()
    with zipfile.ZipFile(checkpoint) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination_root):
                raise ValueError("OpenFOAM checkpoint contains an unsafe path")
        metadata = inspect_checkpoint_metadata(checkpoint, expected_case_id)
        archive.extractall(destination)
    return metadata


def inspect_checkpoint_metadata(
    checkpoint: Path, expected_case_id: str
) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(checkpoint) as archive:
            metadata = json.loads(archive.read(CHECKPOINT_METADATA))
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise ValueError("OpenFOAM checkpoint metadata is missing or invalid") from exc
    if not isinstance(metadata, dict):
        raise ValueError("OpenFOAM checkpoint metadata is missing or invalid")
    if metadata.get("case_id") != expected_case_id:
        raise ValueError("OpenFOAM checkpoint belongs to a different case fingerprint")
    return metadata


def _checkpoint_files(case_root: Path) -> list[Path]:
    latest = _latest_time(case_root)
    selected_roots = [
        case_root / "constant" / "fluid",
        case_root / "constant" / "solid",
        case_root / "constant" / "regionProperties",
        case_root / "system",
    ]
    if latest is not None:
        selected_roots.append(case_root / f"{latest:g}")
        matching = [
            child
            for child in case_root.iterdir()
            if child.is_dir()
            and child.name not in {"constant", "system"}
            and not child.name.startswith("processor")
            and _is_same_time(child.name, latest)
        ]
        selected_roots.extend(matching)
    selected_roots.extend(
        case_root / name
        for name in (
            "case.json",
            "solver-history.log",
            "mesh-history.log",
            CHECKPOINT_METADATA,
        )
    )
    files: set[Path] = set()
    for root in selected_roots:
        if root.is_file():
            files.add(root)
        elif root.is_dir():
            files.update(path for path in root.rglob("*") if path.is_file())
    return sorted(files)


def _is_same_time(name: str, expected: float) -> bool:
    try:
        return abs(float(name) - expected) <= max(1e-12, abs(expected) * 1e-10)
    except ValueError:
        return False


def _write_checkpoint(
    case_root: Path,
    target: Path,
    metadata: dict[str, Any],
) -> None:
    metadata_path = case_root / CHECKPOINT_METADATA
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    temporary = target.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _checkpoint_files(case_root):
            archive.write(path, path.relative_to(case_root))
    temporary.replace(target)


def _report_if_present(
    repository: ArtifactRepository, run_id: str
) -> dict[str, Any] | None:
    try:
        report = repository.cae_artifact_path(run_id, "solve-report.json")
    except FileNotFoundError:
        return None
    return json.loads(report.read_text(encoding="utf-8"))


def run_openfoam_solve(
    request: OpenFoamSolveRequest,
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
    run_id = repository.version(
        {
            "case_id": case_id,
            "request": request.model_dump(mode="json"),
            "contract": SOLVE_CONTRACT_VERSION,
        },
        "solve",
    )
    previous = _report_if_present(repository, run_id)
    if previous is not None:
        shutil.rmtree(repository.cae_work_path(run_id), ignore_errors=True)
        return previous

    required = [*mesh_required_commands(), "chtMultiRegionFoam"]
    if request.parallel_processes > 1:
        required.extend(["topoSet", "decomposePar", "reconstructPar", "mpirun"])
    missing_commands = [command for command in required if shutil.which(command) is None]
    execution_status = "environment_unavailable"
    detail: str | None = None
    mesh_log = ""
    solver_log = ""
    infrastructure_log = ""
    checkpoint_restored = False
    workspace_recovered = False
    checkpoint_created = False
    latest_time_s: float | None = None
    mesh_validation = validate_region_mesh("", request.criteria)
    work_root = repository.cae_work_path(run_id)
    case_root = work_root / "case"
    started = time.monotonic()

    if not missing_commands:
        local_metadata: dict[str, Any] | None = None
        if case_root.exists() and (case_root / "mesh-history.log").is_file():
            metadata_path = case_root / CHECKPOINT_METADATA
            if metadata_path.is_file():
                try:
                    local_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    local_metadata = None
            if local_metadata is None or local_metadata.get("case_id") == case_id:
                workspace_recovered = True
        if not workspace_recovered:
            if case_root.exists():
                shutil.rmtree(case_root)
            case_root.mkdir(parents=True)
        try:
            if workspace_recovered:
                checkpoint_restored = bool(request.resume_from_run_id)
                mesh_log = (case_root / "mesh-history.log").read_text(encoding="utf-8")
                mesh_validation = (
                    local_metadata["mesh_validation"]
                    if local_metadata and "mesh_validation" in local_metadata
                    else validate_region_mesh(mesh_log, request.criteria)
                )
            elif request.resume_from_run_id:
                checkpoint = repository.cae_artifact_path(
                    request.resume_from_run_id, CHECKPOINT_FILENAME
                )
                checkpoint_metadata = _safe_extract_checkpoint(
                    checkpoint, case_root, case_id
                )
                checkpoint_restored = True
                mesh_validation = checkpoint_metadata["mesh_validation"]
                mesh_log_path = case_root / "mesh-history.log"
                mesh_log = (
                    mesh_log_path.read_text(encoding="utf-8")
                    if mesh_log_path.exists()
                    else ""
                )
            else:
                package = repository.cae_artifact_path(case_id, f"{case_id}.zip")
                _extract_case_package(package, case_root)
                allrun = case_root / "Allrun"
                allrun.chmod(0o755)
                code, mesh_log, timed_out = _run_process(
                    [str(allrun)], case_root, request.max_runtime_seconds
                )
                (case_root / "mesh-history.log").write_text(mesh_log, encoding="utf-8")
                mesh_validation = validate_region_mesh(mesh_log, request.criteria)
                if timed_out:
                    execution_status = "preprocessing_timed_out"
                elif code != 0:
                    execution_status = "preprocessing_failed"
                elif not mesh_validation["acceptance_passed"]:
                    execution_status = "mesh_validation_failed"

            if checkpoint_restored or execution_status == "environment_unavailable":
                if not mesh_validation["acceptance_passed"]:
                    execution_status = "mesh_validation_failed"
                else:
                    configure_production_case(case_root, request)
                    current_time = _latest_time(case_root) or 0.0
                    if current_time >= request.target_end_time_s:
                        execution_status = "target_already_reached"
                    else:
                        remaining = request.max_runtime_seconds - (
                            time.monotonic() - started
                        )
                        parallel_ready = False
                        if remaining <= 0:
                            execution_status = "timed_out"
                        else:
                            if request.parallel_processes > 1:
                                interface_sets_ready = True
                                for region in ("fluid", "solid"):
                                    code, output, timed_out = _run_process(
                                        [
                                            "topoSet",
                                            "-region",
                                            region,
                                        ],
                                        case_root,
                                        remaining,
                                    )
                                    infrastructure_log += output
                                    if timed_out or code != 0:
                                        interface_sets_ready = False
                                        execution_status = "interface_constraint_failed"
                                        break
                                    remaining = request.max_runtime_seconds - (
                                        time.monotonic() - started
                                    )
                            if request.parallel_processes > 1 and interface_sets_ready:
                                code, output, timed_out = _run_process(
                                    ["decomposePar", "-allRegions", "-force"],
                                    case_root,
                                    remaining,
                                )
                                infrastructure_log += output
                                if timed_out:
                                    execution_status = "decomposition_timed_out"
                                elif code != 0:
                                    execution_status = "decomposition_failed"
                                else:
                                    parallel_ready = True
                                    remaining = request.max_runtime_seconds - (
                                        time.monotonic() - started
                                    )
                            if request.parallel_processes == 1:
                                command = ["chtMultiRegionFoam"]
                            elif parallel_ready:
                                command = [
                                    "mpirun",
                                    "--allow-run-as-root",
                                    "-np",
                                    str(request.parallel_processes),
                                    "chtMultiRegionFoam",
                                    "-parallel",
                                ]
                            else:
                                command = []
                            if command:
                                code, solver_log, timed_out = _run_process(
                                    command, case_root, remaining
                                )
                                execution_status = (
                                    "timed_out"
                                    if timed_out
                                    else "completed"
                                    if code == 0
                                    else "solver_failed"
                                )
                            if request.parallel_processes > 1 and any(
                                case_root.glob("processor*")
                            ):
                                processor_time = _processor_latest_time(case_root)
                                reconstruct_timeout = max(
                                    30,
                                    min(
                                        900,
                                        request.max_runtime_seconds
                                        - (time.monotonic() - started),
                                    ),
                                )
                                if processor_time is not None and processor_time > 0:
                                    code, output, _ = _run_process(
                                        [
                                            "reconstructPar",
                                            "-allRegions",
                                            "-time",
                                            f"{processor_time:g}",
                                        ],
                                        case_root,
                                        reconstruct_timeout,
                                    )
                                    infrastructure_log += output
                                    if code != 0 and execution_status == "completed":
                                        execution_status = "reconstruction_failed"
                                for processor in case_root.glob("processor*"):
                                    shutil.rmtree(processor)

            history_path = case_root / "solver-history.log"
            old_history = (
                history_path.read_text(encoding="utf-8")
                if history_path.exists()
                else ""
            )
            solver_history = (old_history + "\n" + solver_log).strip()
            history_path.write_text(solver_history, encoding="utf-8")
            latest_time_s = _latest_time(case_root)
            if mesh_validation["acceptance_passed"] and latest_time_s is not None:
                checkpoint_metadata = {
                    "contract_version": SOLVE_CONTRACT_VERSION,
                    "run_id": run_id,
                    "case_id": case_id,
                    "latest_time_s": latest_time_s,
                    "target_end_time_s": request.target_end_time_s,
                    "parallel_processes": request.parallel_processes,
                    "mesh_validation": mesh_validation,
                    "created_at": datetime.now(UTC).isoformat(),
                }
                checkpoint_target = repository.cae_artifact_write_path(
                    run_id, CHECKPOINT_FILENAME
                )
                _write_checkpoint(case_root, checkpoint_target, checkpoint_metadata)
                checkpoint_created = True
        except FileNotFoundError as exc:
            execution_status = "checkpoint_unavailable"
            detail = str(exc)
            solver_history = ""
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            execution_status = "checkpoint_invalid" if request.resume_from_run_id else "failed"
            detail = str(exc)
            solver_history = ""
    else:
        solver_history = ""

    readiness = validate_response_readiness(
        solver_history,
        request.heat_load_w,
        request.ambient_temperature_c,
        request.criteria,
        allow_results=execution_status
        in {"completed", "target_already_reached"},
    )
    results_available = readiness["results_available"]
    responses = dict(readiness["provisional_responses"])
    responses["provisional"] = not results_available
    responses["results_available"] = results_available
    combined_log = (
        mesh_log
        + "\n--- PRODUCTION INFRASTRUCTURE ---\n"
        + infrastructure_log
        + "\n--- PRODUCTION CHT SOLVE ---\n"
        + solver_history
    )
    if combined_log.strip("\n- "):
        repository.save_cae_artifact(run_id, "solve.log", combined_log[-5_000_000:])

    status = (
        "passed"
        if results_available
        else "completed_unconverged"
        if execution_status in {"completed", "target_already_reached"}
        else execution_status
    )
    result = {
        "solve_run_id": run_id,
        "case_id": case_id,
        "mesh_profile": request.mesh_profile,
        "contract_version": SOLVE_CONTRACT_VERSION,
        "status": status,
        "execution_status": execution_status,
        "detail": detail,
        "missing_commands": missing_commands,
        "checkpoint_restored": checkpoint_restored,
        "workspace_recovered": workspace_recovered,
        "checkpoint_created": checkpoint_created,
        "resumable": checkpoint_created,
        "resumed_from_run_id": request.resume_from_run_id,
        "latest_time_s": latest_time_s,
        "target_end_time_s": request.target_end_time_s,
        "parallel_processes": request.parallel_processes,
        "mesh_validation": mesh_validation,
        "response_readiness": readiness,
        "responses": responses,
        "results_available": results_available,
        "numerically_converged": results_available,
        "mesh_independence_validated": False,
        "design_result_available": False,
        "not_cfd_result": not results_available,
        "generated_at": datetime.now(UTC).isoformat(),
        "downloads": {
            "case_package": case["downloads"]["case_package"],
            "checkpoint": (
                f"/api/v1/cae/{run_id}/artifacts/{CHECKPOINT_FILENAME}"
                if checkpoint_created
                else None
            ),
            "report": f"/api/v1/cae/{run_id}/artifacts/solve-report.json",
            "log": (
                f"/api/v1/cae/{run_id}/artifacts/solve.log"
                if combined_log.strip("\n- ")
                else None
            ),
        },
        "notice": (
            "The production CHT run passed mesh, convergence, temporal-stability, energy-balance, and response gates."
            if results_available
            else "The run is checkpointed when possible, but its provisional values are not CFD results until every numerical gate passes."
        ),
    }
    repository.save_cae_artifact(
        run_id, "solve-report.json", json.dumps(result, indent=2, sort_keys=True)
    )
    shutil.rmtree(work_root, ignore_errors=True)
    return result
