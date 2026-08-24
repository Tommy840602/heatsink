from app.domain.models import DoeRequest
from app.services.doe import generate_doe


def test_lhs_size_bounds_and_reproducibility():
    request = DoeRequest(method="LHS", runs=40, seed=42)
    factors, first = generate_doe(request)
    _, second = generate_doe(request)
    assert len(first) == 40
    assert first == second
    for row in first:
        for factor in factors:
            assert factor.lower <= row[factor.name] <= factor.upper


def test_structured_designs_use_standard_matrix_sizes_and_bounds():
    expected_sizes = {"CCD": 50, "BBD": 46}
    for method, expected_size in expected_sizes.items():
        factors, matrix = generate_doe(DoeRequest(method=method, runs=32, seed=7))
        assert len(matrix) == expected_size
        for row in matrix:
            for factor in factors:
                assert factor.lower <= row[factor.name] <= factor.upper


def test_factorial_designs_cover_full_and_resolution_five_half_fraction():
    expected_sizes = {"Full Factorial": 32, "Fractional Factorial": 16}
    for method, expected_size in expected_sizes.items():
        factors, matrix = generate_doe(DoeRequest(method=method, runs=32, seed=7))
        assert len(matrix) == expected_size
        assert len({tuple(row[factor.name] for factor in factors) for row in matrix}) == expected_size
        for row in matrix:
            for factor in factors:
                assert row[factor.name] in {factor.lower, factor.upper}
