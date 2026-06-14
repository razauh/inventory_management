from __future__ import annotations

import sqlite3
from pathlib import Path

from modules.backup_restore.service import BackupJob, _Callbacks
from modules.backup_restore.validators import validate_backup_destination


class _SqliteOps:
    def __init__(self, source_db: Path) -> None:
        self.source_db = source_db
        self.snapshot_called = False

    def get_db_path(self) -> str:
        return str(self.source_db)

    def get_db_size_bytes(self, path: str) -> int:
        return Path(path).stat().st_size

    def create_consistent_snapshot(self, *args, **kwargs) -> None:
        self.snapshot_called = True

    def quick_check(self, db_path: str) -> bool:
        return True


class _FsOps:
    def __init__(self) -> None:
        self.move_called = False

    def get_free_space_bytes(self, path: str) -> int:
        return 1024 * 1024 * 1024

    def make_temp_file(self, suffix: str = "", dir: str | None = None) -> str:
        return str(Path(dir or ".") / f"snapshot{suffix}")

    def atomic_move(self, src: str, dest: str) -> None:
        self.move_called = True


def test_backup_job_rejects_destination_that_is_active_database_path(tmp_path):
    live_db = tmp_path / "live.imsdb"
    con = sqlite3.connect(live_db)
    try:
        con.execute("CREATE TABLE product(id INTEGER PRIMARY KEY);")
    finally:
        con.close()

    sqlite_ops = _SqliteOps(live_db)
    fsops = _FsOps()
    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(live_db), callbacks)

    assert len(finished) == 1
    ok, message, out_path = finished[0]
    assert ok is False
    assert "active database" in message
    assert out_path is None
    assert sqlite_ops.snapshot_called is False
    assert fsops.move_called is False


def test_backup_job_rejects_raw_active_database_path_before_extension_normalization(tmp_path):
    live_db = tmp_path / "live.db"
    con = sqlite3.connect(live_db)
    try:
        con.execute("CREATE TABLE product(id INTEGER PRIMARY KEY);")
    finally:
        con.close()

    sqlite_ops = _SqliteOps(live_db)
    fsops = _FsOps()
    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(live_db), callbacks)

    assert len(finished) == 1
    ok, message, out_path = finished[0]
    assert ok is False
    assert "active database" in message
    assert out_path is None
    assert sqlite_ops.snapshot_called is False
    assert fsops.move_called is False


def test_validate_backup_destination_rejects_active_database_path(tmp_path):
    live_db = tmp_path / "live.imsdb"
    live_db.write_bytes(b"sqlite placeholder")

    try:
        validate_backup_destination(
            str(live_db),
            db_size=live_db.stat().st_size,
            free_space=1024 * 1024,
            active_db_path=str(live_db),
        )
    except RuntimeError as exc:
        assert "active database" in str(exc)
    else:
        raise AssertionError("Expected active DB destination to be rejected.")
