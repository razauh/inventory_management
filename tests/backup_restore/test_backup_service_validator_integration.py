from __future__ import annotations

from pathlib import Path

import pytest

from inventory_management.modules.backup_restore import service as service_module
from inventory_management.modules.backup_restore.service import BackupJob, _Callbacks


class _SqliteOps:
    def __init__(self, source_db: Path, events: list[str]) -> None:
        self.source_db = source_db
        self.events = events
        self.snapshot_called = False

    def get_db_path(self) -> str:
        return str(self.source_db)

    def get_db_size_bytes(self, path: str) -> int:
        return Path(path).stat().st_size

    def create_consistent_snapshot(self, *args, **kwargs) -> None:
        self.events.append("snapshot")
        self.snapshot_called = True

    def quick_check(self, db_path: str) -> bool:
        return True


class _FsOps:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.move_called = False

    def get_free_space_bytes(self, path: str) -> int:
        return 1024 * 1024 * 1024

    def make_temp_file(self, suffix: str = "", dir: str | None = None) -> str:
        return str(self.tmp_path / f"snapshot{suffix}")

    def atomic_move(self, src: str, dest: str) -> None:
        self.move_called = True


def test_backup_job_uses_central_validators_before_snapshot(tmp_path, monkeypatch):
    source_db = tmp_path / "live.db"
    source_db.write_bytes(b"sqlite placeholder")
    raw_dest = tmp_path / "backup"
    events: list[str] = []

    def validate_source(db_path: str) -> None:
        events.append("source")
        assert db_path == str(source_db)

    def validate_destination(
        dest_file: str,
        db_size: int,
        free_space: int,
        active_db_path: str | None = None,
    ) -> None:
        events.append("destination")
        assert dest_file == str(raw_dest)
        assert db_size == source_db.stat().st_size
        assert free_space == 1024 * 1024 * 1024
        assert active_db_path == str(source_db)

    monkeypatch.setattr(service_module, "validate_backup_source", validate_source)
    monkeypatch.setattr(service_module, "validate_backup_destination", validate_destination)

    sqlite_ops = _SqliteOps(source_db, events)
    fsops = _FsOps(tmp_path)
    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(raw_dest), callbacks)

    assert events == ["source", "destination", "snapshot"]
    assert sqlite_ops.snapshot_called is True
    assert fsops.move_called is True
    assert finished == [
        (True, "Backup completed successfully.", str(raw_dest.with_suffix(".imsdb")))
    ]


@pytest.mark.parametrize("failing_validator", ["source", "destination"])
def test_backup_job_stops_when_central_validator_rejects(
    tmp_path,
    monkeypatch,
    failing_validator,
):
    source_db = tmp_path / "live.db"
    source_db.write_bytes(b"sqlite placeholder")
    events: list[str] = []

    def validate_source(db_path: str) -> None:
        events.append("source")
        if failing_validator == "source":
            raise RuntimeError("centralized source failure")

    def validate_destination(*args, **kwargs) -> None:
        events.append("destination")
        if failing_validator == "destination":
            raise RuntimeError("centralized destination failure")

    monkeypatch.setattr(service_module, "validate_backup_source", validate_source)
    monkeypatch.setattr(service_module, "validate_backup_destination", validate_destination)

    sqlite_ops = _SqliteOps(source_db, events)
    fsops = _FsOps(tmp_path)
    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(
        str(tmp_path / "backup.imsdb"),
        callbacks,
    )

    assert sqlite_ops.snapshot_called is False
    assert fsops.move_called is False
    assert len(finished) == 1
    ok, message, out_path = finished[0]
    assert ok is False
    assert f"centralized {failing_validator} failure" in message
    assert out_path is None


def test_backup_job_lets_destination_validator_reject_final_imsdb_directory(tmp_path):
    source_db = tmp_path / "live.db"
    source_db.write_bytes(b"sqlite placeholder")
    raw_dest = tmp_path / "backup"
    raw_dest.with_suffix(".imsdb").mkdir()
    events: list[str] = []

    sqlite_ops = _SqliteOps(source_db, events)
    fsops = _FsOps(tmp_path)
    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(raw_dest), callbacks)

    assert sqlite_ops.snapshot_called is False
    assert fsops.move_called is False
    assert len(finished) == 1
    ok, message, out_path = finished[0]
    assert ok is False
    assert "Destination path points to a directory" in message
    assert out_path is None
