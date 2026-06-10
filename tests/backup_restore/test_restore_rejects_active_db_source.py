from __future__ import annotations

from pathlib import Path

import pytest

from inventory_management.modules.backup_restore import fsops
from inventory_management.modules.backup_restore.service import RestoreJob, _Callbacks


class _SqliteOps:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self.quick_check_called = False
        self.schema_check_called = False

    def get_db_path(self) -> str:
        return str(self._db_path)

    def quick_check(self, db_path: str) -> bool:
        self.quick_check_called = True
        return True

    def verify_app_schema_compatibility(self, db_path: str):
        self.schema_check_called = True
        return True, []


class _FsOps:
    def __init__(self) -> None:
        self.safety_copy_called = False
        self.replace_called = False

    def safety_copy_current_db(self, db_path: str, timestamp: str) -> str:
        self.safety_copy_called = True
        return str(Path(db_path).parent / f"pre-restore-{timestamp}")

    def replace_db_with(self, source_db_file: str, target_db_path: str) -> None:
        self.replace_called = True


class _AppDbManager:
    def __init__(self) -> None:
        self.close_called = False
        self.open_called = False

    def close_all(self) -> None:
        self.close_called = True

    def open(self) -> None:
        self.open_called = True


def test_restore_job_rejects_active_database_before_validation_or_swap(tmp_path):
    live_db = tmp_path / "live.imsdb"
    live_db.write_bytes(b"not used because path validation runs first")
    sqlite_ops = _SqliteOps(live_db)
    fs_ops = _FsOps()
    app_db_manager = _AppDbManager()
    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    RestoreJob(
        sqlite_ops=sqlite_ops,
        fsops=fs_ops,
        app_db_manager=app_db_manager,
    )._run(str(tmp_path / "." / live_db.name), callbacks)

    assert finished
    ok, message, path = finished[0]
    assert ok is False
    assert path is None
    assert "active database or its WAL/SHM files" in message
    assert sqlite_ops.quick_check_called is False
    assert sqlite_ops.schema_check_called is False
    assert fs_ops.safety_copy_called is False
    assert fs_ops.replace_called is False
    assert app_db_manager.close_called is False
    assert app_db_manager.open_called is False
    assert live_db.exists()


@pytest.mark.parametrize("source_suffix", ["", "-wal", "-shm"])
def test_replace_db_with_rejects_active_database_family_without_removing_target(tmp_path, source_suffix):
    target = tmp_path / "live.db"
    target.write_text("current")
    source = Path(str(target) + source_suffix)
    if source != target:
        source.write_text("sidecar")

    with pytest.raises(RuntimeError, match="active database or its WAL/SHM files"):
        fsops.replace_db_with(str(source), str(target))

    assert target.read_text() == "current"
    assert source.exists()
