import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backup_engineering_artifacts import backup, restore


def test_artifact_backup_round_trip_and_checksum(tmp_path):
    source = tmp_path / "data"
    (source / "experiments").mkdir(parents=True)
    (source / "experiments" / "dataset.parquet").write_bytes(b"immutable-parquet")
    archive = tmp_path / "backup.tar.gz"
    backup(source, archive)
    restored = tmp_path / "restored"
    restore(archive, restored)
    assert (restored / "experiments" / "dataset.parquet").read_bytes() == b"immutable-parquet"
