import hashlib
import io
import json
from pathlib import Path
import runpy
import tarfile

import pytest


ROOT = Path(__file__).parents[2]
STATE = runpy.run_path(str(ROOT / "scripts" / "observability_state.py"))
validate_archive = STATE["validate_archive"]
restore = STATE["restore"]


def archive_with_member(path: Path, name: str, kind: str = "file") -> str:
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        if kind == "symlink":
            member.type = tarfile.SYMTYPE
            member.linkname = "/etc/passwd"
            archive.addfile(member)
        else:
            body = b"durable-observability-state"
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_archive_validation_accepts_checksummed_regular_files(tmp_path):
    archive = tmp_path / "state.tar.gz"
    checksum = archive_with_member(archive, "./silences")

    validate_archive(archive, checksum)


@pytest.mark.parametrize(
    ("name", "kind"),
    (
        ("../../outside", "file"),
        ("/absolute/path", "file"),
        ("./unsafe-link", "symlink"),
    ),
)
def test_archive_validation_rejects_unsafe_members(tmp_path, name, kind):
    archive = tmp_path / "state.tar.gz"
    checksum = archive_with_member(archive, name, kind)

    with pytest.raises(RuntimeError):
        validate_archive(archive, checksum)


def test_archive_validation_rejects_checksum_mismatch(tmp_path):
    archive = tmp_path / "state.tar.gz"
    archive_with_member(archive, "./nflog")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        validate_archive(archive, "0" * 64)


def test_restore_requires_explicit_empty_volume_confirmation(tmp_path):
    with pytest.raises(RuntimeError, match="confirm-empty-volumes"):
        restore("thermoform", tmp_path, confirm_empty_volumes=False)


def test_restore_keeps_schema_one_backups_compatible(tmp_path, monkeypatch):
    entries = {}
    for key in ("prometheus-data", "alertmanager-data"):
        archive = tmp_path / f"{key}.tar.gz"
        entries[key] = {
            "archive": archive.name,
            "docker_volume": f"old-{key}",
            "sha256": archive_with_member(archive, f"./{key}"),
        }
    tmp_path.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": "thermoform",
                "volumes": entries,
            }
        ),
        encoding="utf-8",
    )
    restored = []
    globals_ = restore.__globals__
    monkeypatch.setitem(globals_, "resolve_volume", lambda _project, key: f"new-{key}")
    monkeypatch.setitem(globals_, "require_volume_idle", lambda _volume: None)
    monkeypatch.setitem(globals_, "require_volume_empty", lambda _volume: None)
    monkeypatch.setitem(
        globals_,
        "restore_volume",
        lambda volume, archive: restored.append((volume, archive.name)),
    )

    restore("thermoform", tmp_path, confirm_empty_volumes=True)

    assert restored == [
        ("new-prometheus-data", "prometheus-data.tar.gz"),
        ("new-alertmanager-data", "alertmanager-data.tar.gz"),
    ]


def test_restore_keeps_schema_two_backups_compatible(tmp_path, monkeypatch):
    keys = ("prometheus-data", "alertmanager-data", "alertmanager-2-data")
    entries = {}
    for key in keys:
        archive = tmp_path / f"{key}.tar.gz"
        entries[key] = {
            "archive": archive.name,
            "docker_volume": f"old-{key}",
            "sha256": archive_with_member(archive, f"./{key}"),
        }
    tmp_path.joinpath("manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "project_name": "thermoform",
                "volumes": entries,
            }
        ),
        encoding="utf-8",
    )
    restored = []
    globals_ = restore.__globals__
    monkeypatch.setitem(globals_, "resolve_volume", lambda _project, key: f"new-{key}")
    monkeypatch.setitem(globals_, "require_volume_idle", lambda _volume: None)
    monkeypatch.setitem(globals_, "require_volume_empty", lambda _volume: None)
    monkeypatch.setitem(
        globals_,
        "restore_volume",
        lambda volume, archive: restored.append((volume, archive.name)),
    )

    restore("thermoform", tmp_path, confirm_empty_volumes=True)

    assert restored == [
        (f"new-{key}", f"{key}.tar.gz")
        for key in keys
    ]
