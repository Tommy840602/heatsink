import hashlib
import io
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
