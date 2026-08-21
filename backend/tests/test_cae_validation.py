from app.domain.cae import CaeAcceptanceCriteria
from app.services.cae_validation import validate_cae_run, validate_region_mesh


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
