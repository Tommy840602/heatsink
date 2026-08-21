from typing import Any

from rq import get_current_job

from app.repositories.artifacts import ArtifactRepository


def _progress(value: int, stage: str) -> None:
    job = get_current_job()
    if job is None:
        return
    job.meta.update({"progress": value, "stage": stage})
    job.save_meta()


def execute_job(task: str, payload: dict[str, Any]) -> dict[str, Any]:
    """RQ entrypoint. Validation is intentionally repeated inside the worker process."""
    repository = ArtifactRepository()
    _progress(5, "validating_input")
    if task == "phase1":
        from app.domain.phase1 import Phase1WorkflowRequest
        from app.services.workflow import run_phase1

        _progress(15, "doe_simulation_training_optimization")
        result = run_phase1(Phase1WorkflowRequest.model_validate(payload), repository)
        _progress(100, "completed")
        return result
    if task == "phase2":
        from app.domain.phase2 import Phase2WorkflowRequest
        from app.services.phase2_workflow import run_phase2

        _progress(15, "bayesian_learning_and_cad")
        result = run_phase2(Phase2WorkflowRequest.model_validate(payload), repository)
        _progress(100, "completed")
        return result
    if task == "cae":
        from app.domain.cae import OpenFoamCaseRequest
        from app.services.openfoam import prepare_openfoam_case

        _progress(25, "generating_cad_and_case")
        result = prepare_openfoam_case(OpenFoamCaseRequest.model_validate(payload), repository)
        _progress(100, "completed")
        return result
    if task == "cae_benchmark":
        from app.domain.cae import OpenFoamBenchmarkRequest
        from app.services.openfoam_benchmark import run_openfoam_benchmark

        _progress(15, "checking_openfoam_environment")
        result = run_openfoam_benchmark(OpenFoamBenchmarkRequest.model_validate(payload), repository)
        _progress(100, "completed")
        return result
    if task == "cae_mesh":
        from app.domain.cae import OpenFoamMeshRequest
        from app.services.openfoam_mesh import run_openfoam_mesh

        _progress(10, "generating_watertight_geometry")
        result = run_openfoam_mesh(OpenFoamMeshRequest.model_validate(payload), repository)
        _progress(100, "completed")
        return result
    if task == "cae_smoke":
        from app.domain.cae import OpenFoamSmokeRequest
        from app.services.openfoam_smoke import run_openfoam_smoke

        _progress(10, "meshing_and_initializing_cht_fields")
        result = run_openfoam_smoke(OpenFoamSmokeRequest.model_validate(payload), repository)
        _progress(100, "completed")
        return result
    if task == "cae_solve":
        from app.domain.cae import OpenFoamSolveRequest
        from app.services.openfoam_solve import run_openfoam_solve

        _progress(10, "restoring_checkpoint_or_meshing")
        result = run_openfoam_solve(OpenFoamSolveRequest.model_validate(payload), repository)
        _progress(100, "completed")
        return result
    raise ValueError(f"Unsupported job task: {task}")
