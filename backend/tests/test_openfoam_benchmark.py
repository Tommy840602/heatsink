from app.domain.cae import OpenFoamBenchmarkRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.openfoam_benchmark import run_openfoam_benchmark


def test_benchmark_reports_unavailable_environment_without_fake_results(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.openfoam_benchmark._tutorial_path", lambda: None)
    monkeypatch.setattr("app.services.openfoam_benchmark.shutil.which", lambda _command: None)

    result = run_openfoam_benchmark(
        OpenFoamBenchmarkRequest(), ArtifactRepository(tmp_path)
    )

    assert result["status"] == "environment_unavailable"
    assert result["solver_executed"] is False
    assert result["benchmark_validated"] is False
    assert result["results_available"] is False
    assert result["not_design_cfd_result"] is True
    assert result["validation"]["acceptance_passed"] is False
    assert ArtifactRepository(tmp_path).cae_artifact_path(
        result["benchmark_id"], "report.json"
    ).exists()
