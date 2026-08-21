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
        rf"Solving for\s+([^,]+),\s+Initial residual\s*=\s*({FLOAT}),\s+Final residual\s*=\s*({FLOAT})",
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
