import re
from typing import Any

from app.domain.cae import CaeAcceptanceCriteria


FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def _last_number(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    if not matches:
        return None
    value = matches[-1]
    if isinstance(value, tuple):
        value = value[-1]
    return float(value)


def _metric(name: str, text: str) -> float | None:
    return _last_number(rf"\b{name}\s*=\s*({FLOAT})", text)


def validate_cae_run(
    check_mesh_log: str,
    solver_log: str,
    criteria: CaeAcceptanceCriteria | None = None,
) -> dict[str, Any]:
    criteria = criteria or CaeAcceptanceCriteria()
    max_non_orthogonality = _last_number(
        rf"non-orthogonality\s+Max:\s*({FLOAT})", check_mesh_log
    )
    max_skewness = _last_number(rf"Max\s+skewness\s*=\s*({FLOAT})", check_mesh_log)
    cell_count = _last_number(rf"\bcells:\s*({FLOAT})", check_mesh_log)
    mesh_ok_marker = bool(re.search(r"\bMesh OK\.", check_mesh_log, flags=re.IGNORECASE))
    mesh_passed = bool(
        mesh_ok_marker
        and max_non_orthogonality is not None
        and max_non_orthogonality <= criteria.max_non_orthogonality
        and max_skewness is not None
        and max_skewness <= criteria.max_skewness
    )

    residual_matches = re.findall(
        rf"Solving for[ \t]+([^,\r\n]+),[ \t]+Initial residual[ \t]*=[ \t]*({FLOAT}),[ \t]+Final residual[ \t]*=[ \t]*({FLOAT})",
        solver_log,
        flags=re.IGNORECASE,
    )
    residuals = [
        {"field": field.strip(), "initial": float(initial), "final": float(final)}
        for field, initial, final in residual_matches
    ]
    latest_by_field: dict[str, dict[str, float | str]] = {}
    for item in residuals:
        latest_by_field[str(item["field"])] = item
    max_final_residual = max(
        (float(item["final"]) for item in latest_by_field.values()), default=None
    )
    end_marker = bool(re.search(r"(?:^|\n)End\s*(?:\n|$)", solver_log))
    convergence_passed = bool(
        end_marker
        and len(residuals) >= criteria.min_residual_samples
        and max_final_residual is not None
        and max_final_residual <= criteria.max_final_residual
    )

    t_max_c = _metric("t_max_c", solver_log)
    pressure_drop_pa = _metric("pressure_drop_pa", solver_log)
    heat_in_w = _metric("heat_in_w", solver_log)
    heat_out_w = _metric("heat_out_w", solver_log)
    energy_imbalance_percent = None
    if heat_in_w is not None and heat_out_w is not None:
        energy_imbalance_percent = abs(heat_in_w - heat_out_w) / max(abs(heat_in_w), 1e-12) * 100
    energy_passed = bool(
        energy_imbalance_percent is not None
        and energy_imbalance_percent <= criteria.max_energy_imbalance_percent
    )
    response_metrics_present = t_max_c is not None and pressure_drop_pa is not None
    acceptance_passed = bool(
        mesh_passed and convergence_passed and energy_passed and response_metrics_present
    )

    return {
        "acceptance_passed": acceptance_passed,
        "gates": {
            "mesh_quality": {
                "passed": mesh_passed,
                "mesh_ok_marker": mesh_ok_marker,
                "cell_count": int(cell_count) if cell_count is not None else None,
                "max_non_orthogonality": max_non_orthogonality,
                "limit": criteria.max_non_orthogonality,
                "max_skewness": max_skewness,
                "skewness_limit": criteria.max_skewness,
            },
            "convergence": {
                "passed": convergence_passed,
                "end_marker": end_marker,
                "sample_count": len(residuals),
                "minimum_samples": criteria.min_residual_samples,
                "max_final_residual": max_final_residual,
                "limit": criteria.max_final_residual,
                "latest_by_field": latest_by_field,
            },
            "energy_balance": {
                "passed": energy_passed,
                "heat_in_w": heat_in_w,
                "heat_out_w": heat_out_w,
                "imbalance_percent": energy_imbalance_percent,
                "limit_percent": criteria.max_energy_imbalance_percent,
            },
            "response_metrics": {
                "passed": response_metrics_present,
                "t_max_c": t_max_c,
                "pressure_drop_pa": pressure_drop_pa,
            },
        },
        "residuals": residuals[-50:],
    }


def validate_region_mesh(
    mesh_log: str,
    criteria: CaeAcceptanceCriteria | None = None,
) -> dict[str, Any]:
    criteria = criteria or CaeAcceptanceCriteria()
    markers = list(
        re.finditer(r"(?m)^Mesh stats[ \t]+(fluid|solid)[ \t]*$", mesh_log)
    )
    regions: dict[str, dict[str, Any]] = {}
    for index, marker in enumerate(markers):
        name = marker.group(1)
        end = markers[index + 1].start() if index + 1 < len(markers) else len(mesh_log)
        section = mesh_log[marker.end() : end]
        cell_count = _last_number(rf"(?m)^\s*cells:\s*({FLOAT})", section)
        non_orthogonality = _last_number(
            rf"non-orthogonality\s+Max:\s*({FLOAT})", section
        )
        skewness = _last_number(rf"Max\s+skewness\s*=\s*({FLOAT})", section)
        concave_cells = _last_number(
            rf"Concave cells.*?number of cells:\s*({FLOAT})", section
        ) or 0.0
        low_determinant_cells = _last_number(
            rf"small determinant.*?number of cells:\s*({FLOAT})", section
        ) or 0.0
        denominator = max(cell_count or 0.0, 1.0)
        concave_percent = concave_cells / denominator * 100
        low_determinant_percent = low_determinant_cells / denominator * 100
        passed = bool(
            cell_count
            and non_orthogonality is not None
            and non_orthogonality <= criteria.max_non_orthogonality
            and skewness is not None
            and skewness <= criteria.max_skewness
            and concave_percent <= criteria.max_concave_cell_percent
            and low_determinant_percent <= criteria.max_low_determinant_cell_percent
        )
        regions[name] = {
            "passed": passed,
            "cell_count": int(cell_count) if cell_count is not None else None,
            "max_non_orthogonality": non_orthogonality,
            "max_skewness": skewness,
            "concave_cells": int(concave_cells),
            "concave_cell_percent": concave_percent,
            "low_determinant_cells": int(low_determinant_cells),
            "low_determinant_cell_percent": low_determinant_percent,
        }

    geometry_closed = "Surface is closed. All edges connected to two faces." in mesh_log
    regions_split = bool(
        re.search(r"Number of regions:\s*2", mesh_log)
        and "fluid_to_solid" in mesh_log
        and "solid_to_fluid" in mesh_log
        and set(regions) == {"fluid", "solid"}
    )
    region_quality = bool(
        set(regions) == {"fluid", "solid"}
        and all(item["passed"] for item in regions.values())
    )
    acceptance_passed = bool(geometry_closed and regions_split and region_quality)
    return {
        "acceptance_passed": acceptance_passed,
        "gates": {
            "watertight_union_geometry": geometry_closed,
            "region_interfaces": regions_split,
            "region_mesh_quality": region_quality,
        },
        "limits": {
            "max_non_orthogonality": criteria.max_non_orthogonality,
            "max_skewness": criteria.max_skewness,
            "max_concave_cell_percent": criteria.max_concave_cell_percent,
            "max_low_determinant_cell_percent": criteria.max_low_determinant_cell_percent,
        },
        "regions": regions,
    }


def validate_solver_smoke(solver_log: str) -> dict[str, Any]:
    fatal_error = bool(re.search(r"FOAM FATAL", solver_log, flags=re.IGNORECASE))
    end_marker = bool(re.search(r"(?:^|\n)End\s*(?:\n|$)", solver_log))
    fluid_region = bool(
        re.search(
            r"(?:fluid region[ \t]+fluid|fluid mesh for region[ \t]+fluid)",
            solver_log,
            re.IGNORECASE,
        )
    )
    solid_region = bool(
        re.search(
            r"(?:solid region[ \t]+solid|solid mesh for region[ \t]+solid)",
            solver_log,
            re.IGNORECASE,
        )
    )
    residual_fields = re.findall(
        r"Solving for[ \t]+([^,\r\n]+),[ \t]+Initial residual", solver_log, re.IGNORECASE
    )
    solved_fields = sorted({field.strip() for field in residual_fields})
    enthalpy_solved = "h" in solved_fields
    momentum_solved = any(field in solved_fields for field in ("Ux", "Uy", "Uz", "U"))
    heat_source_initialized = bool(
        re.search(r"Source:\s*heatSource", solver_log, flags=re.IGNORECASE)
    )
    coupled_energy_solved = bool(
        re.search(r"Solving energy coupled regions", solver_log, flags=re.IGNORECASE)
    )
    passed = bool(
        not fatal_error
        and end_marker
        and fluid_region
        and solid_region
        and enthalpy_solved
        and momentum_solved
        and heat_source_initialized
        and coupled_energy_solved
    )
    return {
        "passed": passed,
        "fatal_error": fatal_error,
        "end_marker": end_marker,
        "fluid_region_initialized": fluid_region,
        "solid_region_initialized": solid_region,
        "enthalpy_solved": enthalpy_solved,
        "momentum_solved": momentum_solved,
        "heat_source_initialized": heat_source_initialized,
        "coupled_energy_solved": coupled_energy_solved,
        "residual_sample_count": len(residual_fields),
        "solved_fields": solved_fields,
    }
