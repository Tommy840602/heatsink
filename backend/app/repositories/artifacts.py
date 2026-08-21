import hashlib
import json
import os
from pathlib import Path
from typing import Any

import joblib


class ArtifactRepository:
    def __init__(self, root: str | Path | None = None):
        configured = root or os.getenv("THERMOFORM_ARTIFACT_DIR", "data")
        self.root = Path(configured)

    @staticmethod
    def version(payload: Any, prefix: str) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:12]}"

    def save_dataset(self, records: list[dict[str, Any]]) -> str:
        version = self.version(records, "dataset")
        path = self.root / "experiments" / f"{version}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
        return version

    def save_model(self, model_id: str, bundle: dict[str, Any], metadata: dict[str, Any]) -> None:
        directory = self.root / "models" / model_id
        directory.mkdir(parents=True, exist_ok=True)
        model_path = directory / "bundle.joblib"
        metadata_path = directory / "metadata.json"
        if not model_path.exists():
            joblib.dump(bundle, model_path)
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    def load_model(self, model_id: str) -> dict[str, Any]:
        path = self.root / "models" / model_id / "bundle.joblib"
        if not path.exists():
            raise FileNotFoundError(model_id)
        return joblib.load(path)

    def load_metadata(self, model_id: str) -> dict[str, Any]:
        path = self.root / "models" / model_id / "metadata.json"
        if not path.exists():
            raise FileNotFoundError(model_id)
        return json.loads(path.read_text(encoding="utf-8"))
