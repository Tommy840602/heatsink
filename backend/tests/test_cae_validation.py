from app.domain.cae import CaeAcceptanceCriteria
from app.services.cae_validation import (
    extract_provisional_responses,
    validate_cae_run,
    validate_region_mesh,
    validate_response_readiness,
    validate_solver_smoke,
)


CHECK_MESH_OK = """
Mesh stats
    cells:            184320
Mesh non-orthogonality Max: 42 average: 8.4
Max skewness = 2.1 OK.
Mesh OK.
"""


SOLVER_OK = """
Solving for T, Initial residual = 0.01, Final residual = 0.001, No Iterations 2
Solving for p_rgh, Initial residual = 0.02, Final residual = 0.0008, No Iterations 2
Solving for T, Initial residual = 0.001, Final residual = 0.00001, No Iterations 1
Solving for p_rgh, Initial residual = 0.0008, Final residual = 0.00002, No Iterations 1
THERMOFORM_METRIC t_max_c=71.4 pressure_drop_pa=18.2 heat_in_w=100 heat_out_w=98.5
End
"""


def test_cae_acceptance_requires_and_passes_all_four_gates():
    report = validate_cae_run(
        CHECK_MESH_OK,
        SOLVER_OK,
        CaeAcceptanceCriteria(min_residual_samples=4),
    )
    assert report["acceptance_passed"] is True
    assert report["gates"]["mesh_quality"]["cell_count"] == 184320
    assert report["gates"]["convergence"]["max_final_residual"] == 0.00002
    assert report["gates"]["energy_balance"]["imbalance_percent"] == 1.5
    assert report["gates"]["response_metrics"]["t_max_c"] == 71.4


def test_cae_acceptance_rejects_missing_energy_and_response_metrics():
    report = validate_cae_run(CHECK_MESH_OK, SOLVER_OK.split("THERMOFORM_METRIC")[0] + "End\n")
    assert report["gates"]["mesh_quality"]["passed"] is True
    assert report["gates"]["energy_balance"]["passed"] is False
    assert report["gates"]["response_metrics"]["passed"] is False
    assert report["acceptance_passed"] is False


def test_residual_field_names_do_not_capture_region_prefix_lines():
    solver_log = """
fluid region topAir
GAMG:  Solving for p_rgh, Initial residual = 8.1e-5, Final residual = 3.5e-7, No Iterations 2
solid region heater
DICPCG:  Solving for h, Initial residual = 5.3e-5, Final residual = 4.2e-9, No Iterations 1
End
"""

    report = validate_cae_run(CHECK_MESH_OK, solver_log)

    assert set(report["gates"]["convergence"]["latest_by_field"]) == {"p_rgh", "h"}


def test_region_mesh_acceptance_uses_each_region_and_explicit_cell_percentages():
    mesh_log = """
Surface is closed. All edges connected to two faces.
Number of regions:2
fluid_to_solid
solid_to_fluid
Mesh stats fluid
    cells: 1424649
Mesh non-orthogonality Max: 56.74701 average: 7.35
Max skewness = 1.760847 OK.
Concave cells (using face planes) found, number of cells: 38762
Failed 1 mesh checks.
Mesh stats solid
    cells: 550744
Mesh non-orthogonality Max: 51.48685 average: 8.15
Max skewness = 1.260805 OK.
Concave cells (using face planes) found, number of cells: 25176
Failed 1 mesh checks.
"""
    report = validate_region_mesh(mesh_log)

    assert report["acceptance_passed"] is True
    assert round(report["regions"]["fluid"]["concave_cell_percent"], 3) == 2.721
    assert round(report["regions"]["solid"]["concave_cell_percent"], 3) == 4.571
    assert report["regions"]["solid"]["low_determinant_cells"] == 0


def test_region_mesh_rejects_low_determinant_cells():
    mesh_log = """
Surface is closed. All edges connected to two faces.
Number of regions:2
fluid_to_solid solid_to_fluid
Mesh stats fluid
cells: 1000
Mesh non-orthogonality Max: 30 average: 5
Max skewness = 1 OK.
Mesh stats solid
cells: 1000
Mesh non-orthogonality Max: 30 average: 5
Max skewness = 1 OK.
Cells with small determinant (< 0.001) found, number of cells: 1
"""
    report = validate_region_mesh(mesh_log)

    assert report["regions"]["fluid"]["passed"] is True
    assert report["regions"]["solid"]["passed"] is False
    assert report["acceptance_passed"] is False


def test_solver_smoke_requires_both_regions_momentum_enthalpy_and_clean_end():
    solver_log = """
Solving for fluid region fluid
Source: heatSource
PBiCGStab: Solving for Ux, Initial residual = 0.1, Final residual = 0.001
Solving energy coupled regions
PBiCGStab: Solving for h, Initial residual = 0.1, Final residual = 0.001
Create solid mesh for region solid for time = 0
PCG: Solving for h, Initial residual = 0.1, Final residual = 0.001
End
"""
    report = validate_solver_smoke(solver_log)

    assert report["passed"] is True
    assert report["solved_fields"] == ["Ux", "h"]
    assert report["residual_sample_count"] == 3


def test_solver_smoke_rejects_fatal_or_incomplete_run():
    report = validate_solver_smoke("Solving for fluid region fluid\nFOAM FATAL ERROR\n")

    assert report["passed"] is False
    assert report["fatal_error"] is True


def test_provisional_responses_parse_fields_without_claiming_results():
    solver_log = """
fieldMinMax solidTemperature write:
    max(T) = 348.15 in cell 10
surfaceFieldValue inletPressure write:
    areaAverage(inlet) of p = 100025
surfaceFieldValue outletPressure write:
    areaAverage(outlet) of p = 100000
surfaceFieldValue solidHeatRate write:
    areaIntegrate(solid_to_fluid) of wallHeatFlux = -97.5
"""
    report = extract_provisional_responses(solver_log, 100, 25)

    assert report["metrics_present"] is True
    assert report["t_max_c"] == 75
    assert report["thermal_resistance_k_w"] == 0.5
    assert report["pressure_drop_pa"] == 25
    assert report["heat_out_w"] == 97.5
    assert report["energy_imbalance_percent"] == 2.5
    assert report["results_available"] is False


def test_response_readiness_requires_stability_energy_convergence_and_result_mode():
    samples = []
    for index in range(5):
        samples.append(
            f"""
max(T) = {348.0 + index * 0.02}
areaAverage(inlet) of p = {100025 + index * 0.01}
areaAverage(outlet) of p = 100000
areaIntegrate(solid_to_fluid) of wallHeatFlux = -98
"""
        )
    solver_log = "".join(samples) + """
Solving for Ux, Initial residual = 0.001, Final residual = 0.00001, No Iterations 2
Solving for h, Initial residual = 0.001, Final residual = 0.00001, No Iterations 2
Solving for p_rgh, Initial residual = 0.001, Final residual = 0.00001, No Iterations 2
End
"""
    blocked = validate_response_readiness(solver_log, 100, 25, allow_results=False)
    allowed = validate_response_readiness(solver_log, 100, 25, allow_results=True)

    assert blocked["numerical_gates_passed"] is True
    assert blocked["results_available"] is False
    assert allowed["results_available"] is True
    assert allowed["response_sample_count"] == 5


def test_one_step_response_is_rejected_as_unstable_and_energy_imbalanced():
    solver_log = """
max(T) = 298.15
areaAverage(inlet) of p = 100000
areaAverage(outlet) of p = 100000
areaIntegrate(solid_to_fluid) of wallHeatFlux = -0.000145
Solving for Ux, Initial residual = 1, Final residual = 1e-8, No Iterations 1
Solving for h, Initial residual = 1, Final residual = 1e-8, No Iterations 1
Solving for p_rgh, Initial residual = 1, Final residual = 1e-8, No Iterations 1
End
"""
    report = validate_response_readiness(solver_log, 100, 25, allow_results=True)

    assert report["results_available"] is False
    assert report["gates"]["temporal_stability"] is False
    assert report["gates"]["energy_balance"] is False
