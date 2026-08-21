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
