#!/usr/bin/env python3
"""Generate a versioned DOE matrix from the command line."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.domain.models import DoeRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.doe import generate_doe


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", default="LHS", choices=["LHS", "CCD", "BBD", "Full Factorial", "Fractional Factorial"])
    parser.add_argument("--runs", type=int, default=48)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    factors, matrix = generate_doe(DoeRequest(method=args.method, runs=args.runs, seed=args.seed))
    version = ArtifactRepository().save_dataset(matrix, {"kind": "doe", "method": args.method, "seed": args.seed})
    print(json.dumps({"dataset_version": version, "runs": len(matrix), "factors": [factor.name for factor in factors]}))


if __name__ == "__main__":
    main()
