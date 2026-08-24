#!/usr/bin/env python3
"""Checksum-protected backup/restore for immutable dataset, model, CAD, CAE, and agent artifacts."""

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(source: Path, output: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f"Artifact directory does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as archive:
        archive.add(source, arcname="data", recursive=True)
    manifest = {
        "schema": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "archive": output.name,
        "sha256": checksum(output),
    }
    output.with_suffix(output.suffix + ".sha256.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(manifest))


def restore(archive: Path, target: Path) -> None:
    manifest_path = archive.with_suffix(archive.suffix + ".sha256.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if checksum(archive) != manifest["sha256"]:
        raise SystemExit("Artifact archive checksum mismatch")
    if target.exists() and any(target.iterdir()):
        raise SystemExit("Restore target must be empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thermoform-artifact-restore-") as temporary:
        temporary_root = Path(temporary)
        with tarfile.open(archive, "r:gz") as source:
            members = source.getmembers()
            if any(
                member.name.startswith("/")
                or ".." in Path(member.name).parts
                or member.issym()
                or member.islnk()
                for member in members
            ):
                raise SystemExit("Unsafe archive path")
            source.extractall(temporary_root, members=members)
        shutil.copytree(temporary_root / "data", target, dirs_exist_ok=True)
    print(json.dumps({"restored": str(target), "sha256": manifest["sha256"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("backup")
    create.add_argument("--source", type=Path, default=Path("data"))
    create.add_argument("--output", type=Path, required=True)
    recover = subparsers.add_parser("restore")
    recover.add_argument("--archive", type=Path, required=True)
    recover.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "backup":
        backup(args.source.resolve(), args.output.resolve())
    else:
        restore(args.archive.resolve(), args.target.resolve())


if __name__ == "__main__":
    main()
