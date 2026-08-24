import hashlib
import json
import os
import shutil
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

    def save_dataset(
        self,
        records: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        import pyarrow as pa
        import pyarrow.parquet as pq

        version = self.version(records, "dataset")
        path = self.root / "experiments" / f"{version}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(".parquet.tmp")
            table = pa.Table.from_pylist(records)
            pq.write_table(table, temporary, compression="zstd")
            temporary.replace(path)
            manifest = path.with_suffix(".metadata.json")
            manifest.write_text(
                json.dumps(
                    {
                        "dataset_version": version,
                        "format": "parquet",
                        "compression": "zstd",
                        "rows": len(records),
                        "columns": table.column_names,
                        "artifact": path.name,
                        **(metadata or {}),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        return version

    def load_dataset(self, version: str) -> list[dict[str, Any]]:
        import pyarrow.parquet as pq

        parquet_path = self.root / "experiments" / f"{version}.parquet"
        if parquet_path.exists():
            return pq.read_table(parquet_path).to_pylist()
        legacy_path = self.root / "experiments" / f"{version}.json"
        if legacy_path.exists():
            return json.loads(legacy_path.read_text(encoding="utf-8"))
        raise FileNotFoundError(version)

    def publish_project_view(
        self,
        project_id: str,
        dataset_version: str,
        model_id: str | None = None,
        *,
        dataset_kind: str = "simulation",
    ) -> dict[str, str]:
        """Create immutable, project-scoped hard-link views of shared artifacts."""
        source_dataset = self.root / "experiments" / f"{dataset_version}.parquet"
        project_dataset = (
            self.root
            / "experiments"
            / project_id
            / dataset_version
            / f"{dataset_kind}.parquet"
        )
        project_dataset.parent.mkdir(parents=True, exist_ok=True)
        if source_dataset.exists() and not project_dataset.exists():
            try:
                os.link(source_dataset, project_dataset)
            except OSError:
                shutil.copy2(source_dataset, project_dataset)
        result = {"dataset": str(project_dataset)}
        if model_id:
            source_model = self.root / "models" / model_id
            project_model = self.root / "models" / project_id / model_id
            project_model.mkdir(parents=True, exist_ok=True)
            for filename in ("bundle.joblib", "metadata.json"):
                source = source_model / filename
                target = project_model / filename
                if source.exists() and not target.exists():
                    try:
                        os.link(source, target)
                    except OSError:
                        shutil.copy2(source, target)
            result["model"] = str(project_model)
        return result

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

    def save_agent_run(self, agent_run_id: str, payload: dict[str, Any]) -> Path:
        directory = self.root / "agent" / agent_run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "run.json"
        if not path.exists():
            path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
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
        encoded = content if isinstance(content, bytes) else content.encode("utf-8")
        try:
            with path.open("xb") as artifact:
                artifact.write(encoded)
        except FileExistsError:
            pass
        return path

    def replace_cae_artifact(
        self, case_id: str, filename: str, content: str | bytes
    ) -> Path:
        if Path(filename).name != filename:
            raise ValueError("CAE artifact filename must not contain a path")
        directory = self.root / "cae" / case_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / filename
        temporary = directory / f".{filename}.tmp"
        encoded = content if isinstance(content, bytes) else content.encode("utf-8")
        temporary.write_bytes(encoded)
        temporary.replace(path)
        return path

    def cae_artifact_write_path(self, case_id: str, filename: str) -> Path:
        if Path(filename).name != filename:
            raise ValueError("CAE artifact filename must not contain a path")
        directory = self.root / "cae" / case_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory / filename

    def cae_work_path(self, run_id: str) -> Path:
        if Path(run_id).name != run_id:
            raise ValueError("CAE run ID must not contain a path")
        path = self.root / "cae-work" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cae_artifact_path(self, case_id: str, filename: str) -> Path:
        if Path(filename).name != filename:
            raise FileNotFoundError(filename)
        path = self.root / "cae" / case_id / filename
        if not path.exists():
            raise FileNotFoundError(filename)
        return path

    def list_cae_report_paths(self, filename: str, prefix: str) -> list[Path]:
        if Path(filename).name != filename:
            raise ValueError("CAE report filename must not contain a path")
        directory = self.root / "cae"
        if not directory.exists():
            return []
        return [
            report
            for artifact_directory in directory.iterdir()
            if artifact_directory.is_dir()
            and artifact_directory.name.startswith(prefix)
            and (report := artifact_directory / filename).is_file()
        ]

    def list_cae_artifact_paths(
        self, case_id: str, filename_prefix: str, filename_suffix: str = ".json"
    ) -> list[Path]:
        if Path(case_id).name != case_id:
            raise ValueError("CAE artifact ID must not contain a path")
        if Path(filename_prefix).name != filename_prefix:
            raise ValueError("CAE artifact prefix must not contain a path")
        directory = self.root / "cae" / case_id
        if not directory.is_dir():
            return []
        return [
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.name.startswith(filename_prefix)
            and path.name.endswith(filename_suffix)
        ]
