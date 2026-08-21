import itertools
import random

from app.domain.models import DoeRequest, FactorRange


DEFAULT_FACTORS = [
    FactorRange(name="fin_count", lower=20, upper=60, integer=True),
    FactorRange(name="fin_thickness", lower=0.3, upper=1.0),
    FactorRange(name="fin_height", lower=20, upper=60),
    FactorRange(name="fin_spacing", lower=1.0, upper=4.0),
    FactorRange(name="air_velocity", lower=0.5, upper=5.0),
]


def _scale(value: float, factor: FactorRange) -> float | int:
    scaled = factor.lower + value * (factor.upper - factor.lower)
    return int(round(scaled)) if factor.integer else round(scaled, 5)


def _lhs(request: DoeRequest, factors: list[FactorRange]) -> list[dict[str, float | int]]:
    rng = random.Random(request.seed)
    columns: list[list[float]] = []
    for _ in factors:
        values = [(index + rng.random()) / request.runs for index in range(request.runs)]
        rng.shuffle(values)
        columns.append(values)
    return [
        {factor.name: _scale(columns[col][row], factor) for col, factor in enumerate(factors)}
        for row in range(request.runs)
    ]


def _structured(request: DoeRequest, factors: list[FactorRange]) -> list[dict[str, float | int]]:
    levels = [0.0, 0.5, 1.0]
    candidates = list(itertools.product(levels, repeat=len(factors)))
    if request.method == "BBD":
        candidates = [point for point in candidates if sum(value != 0.5 for value in point) <= 2]
    rng = random.Random(request.seed)
    rng.shuffle(candidates)
    while len(candidates) < request.runs:
        candidates.extend(candidates[: request.runs - len(candidates)])
    return [
        {factor.name: _scale(point[index], factor) for index, factor in enumerate(factors)}
        for point in candidates[: request.runs]
    ]


def generate_doe(request: DoeRequest) -> tuple[list[FactorRange], list[dict[str, float | int]]]:
    factors = request.factors or DEFAULT_FACTORS
    matrix = _lhs(request, factors) if request.method == "LHS" else _structured(request, factors)
    return factors, matrix
