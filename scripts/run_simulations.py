#!/usr/bin/env python3
"""Simulate every design in an immutable DOE dataset."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.domain.models import DesignParameters
from app.repositories.artifacts import ArtifactRepository
from app.services.simulator import SIMULATOR_VERSION, simulate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_version")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise-std", type=float, default=0.0)
    args = parser.parse_args()
    repository = ArtifactRepository()
    inputs = repository.load_dataset(args.dataset_version)
    records = []
    for index, row in enumerate(inputs):
        design = DesignParameters(**row)
        records.append({"run": index + 1, **design.model_dump(), **simulate(design, args.noise_std, args.seed + index).model_dump()})
    version = repository.save_dataset(records, {"kind": "physics_simulation", "source_dataset": args.dataset_version, "simulator_version": SIMULATOR_VERSION, "seed": args.seed, "noise_std": args.noise_std, "not_cfd_result": True})
    print(json.dumps({"dataset_version": version, "runs": len(records), "simulator_version": SIMULATOR_VERSION, "not_cfd_result": True}))


if __name__ == "__main__":
    main()
