#!/usr/bin/env python3
"""Train and compare all surrogate families for one dataset."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.repositories.artifacts import ArtifactRepository
from app.services.surrogates import train_surrogates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_version")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    repository = ArtifactRepository()
    model_id, metrics, selected = train_surrogates(repository.load_dataset(args.dataset_version), args.seed, repository)
    print(json.dumps({"model_id": model_id, "dataset_version": args.dataset_version, "selected_models": selected, "metrics": metrics}))


if __name__ == "__main__":
    main()
