#!/usr/bin/env python3
"""Offline backup and empty-volume restore for observability Compose state."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


ARCHIVE_IMAGE = "alpine:3.22"
SCHEMA_1_VOLUME_KEYS = ("prometheus-data", "alertmanager-data")
SCHEMA_2_VOLUME_KEYS = (*SCHEMA_1_VOLUME_KEYS, "alertmanager-2-data")
VOLUME_KEYS = (
    "prometheus-data",
    "prometheus-2-data",
    "alertmanager-data",
    "alertmanager-2-data",
    "thanos-receive-data",
)
VOLUME_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
MANIFEST_NAME = "manifest.json"


def docker(*args, check=True, input_file=None, output_file=None):
    process = subprocess.run(
        ["docker", *args],
        check=False,
        stdin=input_file,
        stdout=output_file if output_file is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=output_file is None and input_file is None,
    )
    if check and process.returncode != 0:
        stderr = process.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"docker {' '.join(args)} failed: {str(stderr).strip()}")
    return process


def resolve_volume(project_name: str, volume_key: str) -> str:
    result = docker(
        "volume",
        "ls",
        "--filter",
        f"label=com.docker.compose.project={project_name}",
        "--filter",
        f"label=com.docker.compose.volume={volume_key}",
        "--format",
        "{{.Name}}",
    )
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(names) != 1:
        raise RuntimeError(
            f"expected exactly one {volume_key!r} volume for project "
            f"{project_name!r}, found {len(names)}"
        )
    name = names[0]
    if not VOLUME_NAME_PATTERN.fullmatch(name):
        raise RuntimeError(f"Docker returned an unsafe volume name: {name!r}")
    return name


def require_volume_idle(volume_name: str):
    result = docker("ps", "-q", "--filter", f"volume={volume_name}")
    running = [line for line in result.stdout.splitlines() if line.strip()]
    if running:
        raise RuntimeError(
            f"volume {volume_name!r} is mounted by a running container; "
            "stop its service before backup or restore"
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_volume(volume_name: str, destination: Path):
    try:
        with destination.open("xb") as output:
            docker(
                "run",
                "--rm",
                "--volume",
                f"{volume_name}:/source:ro",
                ARCHIVE_IMAGE,
                "tar",
                "-C",
                "/source",
                "-czf",
                "-",
                ".",
                output_file=output,
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    os.chmod(destination, 0o600)


def validate_archive(path: Path, expected_sha256: str):
    if not path.is_file():
        raise RuntimeError(f"backup archive is missing: {path}")
    if sha256(path) != expected_sha256:
        raise RuntimeError(f"backup checksum mismatch: {path.name}")
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = PurePosixPath(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise RuntimeError(f"unsafe archive path: {member.name!r}")
            if member.isdev() or member.issym() or member.islnk():
                raise RuntimeError(f"unsupported archive member: {member.name!r}")


def require_volume_empty(volume_name: str):
    result = docker(
        "run",
        "--rm",
        "--volume",
        f"{volume_name}:/target",
        ARCHIVE_IMAGE,
        "find",
        "/target",
        "-mindepth",
        "1",
        "-maxdepth",
        "1",
        "-print",
        "-quit",
    )
    if result.stdout.strip():
        raise RuntimeError(
            f"restore target {volume_name!r} is not empty; refusing to overwrite state"
        )


def restore_volume(volume_name: str, archive: Path):
    with archive.open("rb") as source:
        docker(
            "run",
            "--rm",
            "--interactive",
            "--volume",
            f"{volume_name}:/target",
            ARCHIVE_IMAGE,
            "tar",
            "-C",
            "/target",
            "-xzf",
            "-",
            input_file=source,
        )


def backup(project_name: str, output_dir: Path):
    output_dir = output_dir.resolve()
    manifest_path = output_dir / MANIFEST_NAME
    if manifest_path.exists():
        raise RuntimeError(f"backup manifest already exists: {manifest_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    volumes = {key: resolve_volume(project_name, key) for key in VOLUME_KEYS}
    for volume_name in volumes.values():
        require_volume_idle(volume_name)
    archives = {}
    for key, volume_name in volumes.items():
        archive_name = f"{key}.tar.gz"
        archive_path = output_dir / archive_name
        archive_volume(volume_name, archive_path)
        archives[key] = {
            "archive": archive_name,
            "docker_volume": volume_name,
            "sha256": sha256(archive_path),
        }
    manifest = {
        "schema_version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_name": project_name,
        "archive_image": ARCHIVE_IMAGE,
        "volumes": archives,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    return manifest_path


def restore(project_name: str, input_dir: Path, confirm_empty_volumes: bool):
    if not confirm_empty_volumes:
        raise RuntimeError("restore requires --confirm-empty-volumes")
    input_dir = input_dir.resolve()
    manifest_path = input_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in {1, 2, 3}:
        raise RuntimeError("unsupported backup manifest schema")
    if manifest.get("project_name") != project_name:
        raise RuntimeError("backup project does not match restore project")
    entries = manifest.get("volumes")
    expected_keys = {
        1: SCHEMA_1_VOLUME_KEYS,
        2: SCHEMA_2_VOLUME_KEYS,
        3: VOLUME_KEYS,
    }[schema_version]
    if not isinstance(entries, dict) or set(entries) != set(expected_keys):
        raise RuntimeError("backup manifest volume set is invalid")
    volumes = {key: resolve_volume(project_name, key) for key in VOLUME_KEYS}
    for volume_name in volumes.values():
        require_volume_idle(volume_name)
        require_volume_empty(volume_name)
    validated = {}
    for key in expected_keys:
        volume_name = volumes[key]
        entry = entries[key]
        if not isinstance(entry, dict):
            raise RuntimeError(f"backup manifest entry for {key} is invalid")
        archive_name = entry.get("archive")
        if archive_name != f"{key}.tar.gz":
            raise RuntimeError(f"unexpected archive name for {key}")
        archive_path = input_dir / archive_name
        validate_archive(archive_path, entry.get("sha256", ""))
        validated[key] = (volume_name, archive_path)
    for volume_name, archive_path in validated.values():
        restore_volume(volume_name, archive_path)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--project-name", required=True)
    backup_parser.add_argument("--output-dir", required=True, type=Path)
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--project-name", required=True)
    restore_parser.add_argument("--input-dir", required=True, type=Path)
    restore_parser.add_argument("--confirm-empty-volumes", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = backup(args.project_name, args.output_dir)
            print(f"Backup manifest: {result}")
        else:
            restore(args.project_name, args.input_dir, args.confirm_empty_volumes)
            print(f"Restored observability volumes for project {args.project_name}")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, tarfile.TarError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
