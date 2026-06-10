from __future__ import annotations

from pathlib import Path

import pytest

from inventory_management.modules.backup_restore.service import BackupJob, _Callbacks


class _FailingSqliteOps:
    def __init__(self, db_path: Path, fail_at: str) -> None:
        self._db_path = db_path
        self._fail_at = fail_at

    def get_db_path(self) -> str:
        return str(self._db_path)

    def get_db_size_bytes(self, path: str) -> int:
        return Path(path).stat().st_size

    def create_consistent_snapshot(self, dest_path: str, progress_step=None, log=None, verify_mode=None) -> None:
        Path(dest_path).write_bytes(b"partial snapshot")
        if self._fail_at == "snapshot":
            raise RuntimeError("snapshot failed")

    def quick_check(self, db_path: str) -> bool:
        return self._fail_at != "verify"


class _FailingFsOps:
    def __init__(self, tmp_path: Path, fail_at: str) -> None:
        self.temp_snapshot = tmp_path / "snapshot.imsdb"
        self._fail_at = fail_at

    def get_free_space_bytes(self, path: str) -> int:
        return 1024 * 1024

    def make_temp_file(self, suffix: str = "", dir: str | None = None) -> str:
        self.temp_snapshot.touch()
        return str(self.temp_snapshot)

    def atomic_move(self, src: str, dest: str) -> None:
        if self._fail_at == "atomic_move":
            raise RuntimeError("move failed")
        Path(src).replace(dest)


@pytest.mark.parametrize("fail_at", ["snapshot", "verify", "atomic_move"])
def test_backup_job_removes_temp_snapshot_when_backup_fails_after_temp_creation(tmp_path, fail_at):
    live_db = tmp_path / "live.sqlite"
    live_db.write_bytes(b"live db")
    dest = tmp_path / "backup.imsdb"
    sqlite_ops = _FailingSqliteOps(live_db, fail_at)
    fsops = _FailingFsOps(tmp_path, fail_at)
    finished: list[tuple[bool, str, str | None]] = []

    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(dest), callbacks)

    assert finished
    assert finished[0][0] is False
    assert not fsops.temp_snapshot.exists()
