#!/usr/bin/env python3
"""Validate the deletion-safe Thanos Compactor retention contract."""

import argparse
import re


DAYS_PATTERN = re.compile(r"^(0|[1-9][0-9]*)d$")
MINIMUM_DOWNSAMPLING_RETENTION_DAYS = 10


def parse_days(value: str) -> int:
    match = DAYS_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(
            "retention must be expressed as a whole number of days, "
            "for example 0d or 365d"
        )
    return int(match.group(1))


def validate_retention(
    raw: str, five_minutes: str, one_hour: str
) -> tuple[int, int, int]:
    values = tuple(parse_days(value) for value in (raw, five_minutes, one_hour))
    if len(set(values)) != 1:
        raise ValueError(
            "raw, 5m, and 1h retention must be equal to preserve historical zoom"
        )
    if values[0] not in (0,) and values[0] < MINIMUM_DOWNSAMPLING_RETENTION_DAYS:
        raise ValueError("finite retention must be at least 10d for downsampling")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--five-minutes", required=True)
    parser.add_argument("--one-hour", required=True)
    args = parser.parse_args()
    try:
        values = validate_retention(args.raw, args.five_minutes, args.one_hour)
    except ValueError as error:
        parser.error(str(error))
    mode = "forever" if values[0] == 0 else f"{values[0]}d"
    print(f"validated equal Thanos retention: {mode}")


if __name__ == "__main__":
    main()
