#!/usr/bin/env python3
"""Run constrained single- or multi-objective surrogate optimization."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.domain.phase1 import OptimizationRequest
from app.repositories.artifacts import ArtifactRepository
from app.services.optimization import optimize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_id")
    parser.add_argument("--mode", choices=["single", "multi"], default="multi")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    request = OptimizationRequest(model_id=args.model_id, mode=args.mode, objectives=["t_max"] if args.mode == "single" else ["t_max", "pressure_drop", "mass"], seed=args.seed)
    print(json.dumps(optimize(request, ArtifactRepository())))


if __name__ == "__main__":
    main()
