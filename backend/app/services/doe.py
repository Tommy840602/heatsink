from collections.abc import Callable

import numpy as np
from pyDOE3 import bbdesign, ccdesign, lhs

from app.domain.models import DoeRequest, FactorRange


DEFAULT_FACTORS = [
    FactorRange(name="fin_count", lower=20, upper=60, integer=True),
    FactorRange(name="fin_thickness", lower=0.3, upper=1.0),
    FactorRange(name="fin_height", lower=20, upper=60),
    FactorRange(name="fin_spacing", lower=1.0, upper=4.0),
    FactorRange(name="air_velocity", lower=0.5, upper=5.0),
]


def _scale(unit_value: float, factor: FactorRange) -> float | int:
    value = factor.lower + float(unit_value) * (factor.upper - factor.lower)
    return int(round(value)) if factor.integer else round(value, 6)


def _matrix_to_records(matrix: np.ndarray, factors: list[FactorRange]) -> list[dict[str, float | int]]:
    normalized = np.clip((matrix + 1.0) / 2.0, 0.0, 1.0)
    return [
        {factor.name: _scale(row[index], factor) for index, factor in enumerate(factors)}
        for row in normalized
    ]


def _lhs(request: DoeRequest, factors: list[FactorRange]) -> list[dict[str, float | int]]:
    matrix = lhs(
        len(factors),
        samples=request.runs,
        criterion="maximin",
        iterations=40,
        seed=request.seed,
    )
    coded = matrix * 2.0 - 1.0
    return _matrix_to_records(coded, factors)


def _ccd(_: DoeRequest, factors: list[FactorRange]) -> list[dict[str, float | int]]:
    matrix = ccdesign(len(factors), center=(4, 4), alpha="orthogonal", face="ccf")
    return _matrix_to_records(matrix, factors)


def _bbd(_: DoeRequest, factors: list[FactorRange]) -> list[dict[str, float | int]]:
    matrix = bbdesign(len(factors), center=6)
    return _matrix_to_records(matrix, factors)


GENERATORS: dict[str, Callable[[DoeRequest, list[FactorRange]], list[dict[str, float | int]]]] = {
    "LHS": _lhs,
    "CCD": _ccd,
    "BBD": _bbd,
}


def generate_doe(request: DoeRequest) -> tuple[list[FactorRange], list[dict[str, float | int]]]:
    """Generate a standards-based design in physical units and within validated bounds."""
    factors = request.factors or DEFAULT_FACTORS
    return factors, GENERATORS[request.method](request, factors)
