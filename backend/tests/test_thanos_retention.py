from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).parents[2]
RUNTIME = runpy.run_path(str(ROOT / "scripts" / "validate_thanos_retention.py"))
parse_days = RUNTIME["parse_days"]
validate_retention = RUNTIME["validate_retention"]


@pytest.mark.parametrize("value, expected", (("0d", 0), ("10d", 10), ("365d", 365)))
def test_parse_days_accepts_explicit_whole_day_retention(value, expected):
    assert parse_days(value) == expected


@pytest.mark.parametrize(
    "value", ("", "0", "10h", "1.5d", "-1d", "01d", "forever")
)
def test_parse_days_rejects_ambiguous_or_unsafe_durations(value):
    with pytest.raises(ValueError):
        parse_days(value)


def test_retention_allows_non_deleting_default():
    assert validate_retention("0d", "0d", "0d") == (0, 0, 0)


def test_retention_allows_equal_finite_policy_after_downsampling_window():
    assert validate_retention("365d", "365d", "365d") == (365, 365, 365)


def test_retention_rejects_resolution_mismatch():
    with pytest.raises(ValueError, match="must be equal"):
        validate_retention("30d", "90d", "365d")


def test_retention_rejects_policy_shorter_than_downsampling_window():
    with pytest.raises(ValueError, match="at least 10d"):
        validate_retention("9d", "9d", "9d")
