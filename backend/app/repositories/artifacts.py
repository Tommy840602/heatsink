import hashlib
import json
import os
from pathlib import Path
from typing import Any


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

    def load_dataset(self, version: str) -> list[dict[str, Any]]:
        path = self.root / "experiments" / f"{version}.json"
        if not path.exists():
            raise FileNotFoundError(version)
        return json.loads(path.read_text(encoding="utf-8"))

    def save_model(self, model_id: str, bundle: dict[str, Any], metadata: dict[str, Any]) -> None:
        import joblib

        directory = self.root / "models" / model_id
        directory.mkdir(parents=True, exist_ok=True)
        model_path = directory / "bundle.joblib"
        metadata_path = directory / "metadata.json"
        if not model_path.exists():
            joblib.dump(bundle, model_path)
            metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    def load_model(self, model_id: str) -> dict[str, Any]:
        import joblib

        path = self.root / "models" / model_id / "bundle.joblib"
        if not path.exists():
            raise FileNotFoundError(model_id)
        return joblib.load(path)

    def load_metadata(self, model_id: str) -> dict[str, Any]:
        path = self.root / "models" / model_id / "metadata.json"
        if not path.exists():
            raise FileNotFoundError(model_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def save_cad_artifact(self, cad_id: str, filename: str, content: str) -> Path:
        directory = self.root / "cad" / cad_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        if not path.exists():
            path.write_text(content, encoding="utf-8")
        return path

    def cad_artifact_path(self, cad_id: str, filename: str) -> Path:
        if Path(filename).name != filename:
            raise FileNotFoundError(filename)
        path = self.root / "cad" / cad_id / filename
        if not path.exists():
            raise FileNotFoundError(filename)
        return path

    def save_cae_artifact(self, case_id: str, filename: str, content: str | bytes) -> Path:
        if Path(filename).name != filename:
            raise ValueError("CAE artifact filename must not contain a path")
        directory = self.root / "cae" / case_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        if not path.exists():
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        return path

    def cae_artifact_path(self, case_id: str, filename: str) -> Path:
        if Path(filename).name != filename:
            raise FileNotFoundError(filename)
        path = self.root / "cae" / case_id / filename
        if not path.exists():
            raise FileNotFoundError(filename)
        return path
