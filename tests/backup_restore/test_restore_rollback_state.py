from __future__ import annotations

import shutil
from pathlib import Path

from inventory_management.modules.backup_restore import controller as controller_module
from inventory_management.modules.backup_restore.controller import BackupRestoreController
from inventory_management.modules.backup_restore.service import (
    RESTORE_RESTART_REQUIRED_MARKER,
    RestoreJob,
    _Callbacks,
)


class _SqliteOps:
    def __init__(self, db_path: Path, source_path: Path) -> None:
        self._db_path = db_path
        self._source_path = source_path

    def get_db_path(self) -> str:
        return str(self._db_path)

    def quick_check(self, db_path: str) -> bool:
        return Path(db_path) == self._source_path

    def verify_app_schema_compatibility(self, db_path: str):
        return True, []


class _FsOps:
    def safety_copy_current_db(self, db_path: str, timestamp: str) -> str:
        db = Path(db_path)
        safety_dir = db.parent / f"pre-restore-{timestamp}"
        safety_dir.mkdir()
        shutil.copy2(db, safety_dir / db.name)
        return str(safety_dir)

    def replace_db_with(self, source_db_file: str, target_db_path: str) -> None:
        shutil.copy2(source_db_file, target_db_path)


class _AppDbManager:
    def __init__(self) -> None:
        self.open_calls = 0
        self.close_calls = 0

    def close_all(self) -> None:
        self.close_calls += 1

    def open(self) -> None:
        self.open_calls += 1
        if self.open_calls == 2:
            raise RuntimeError("reopen failed")


class _ProgressDialog:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.finished: tuple[bool, str, str | None] | None = None

    def on_log(self, message: str) -> None:
        self.logs.append(message)

    def on_finished(self, ok: bool, message: str, used_path: str | None) -> None:
        self.finished = (ok, message, used_path)


def test_restore_failure_reports_rollback_reopen_failure_after_swap(tmp_path):
    live_db = tmp_path / "live.db"
    source_backup = tmp_path / "backup.imsdb"
    live_db.write_text("original")
    source_backup.write_text("restored")
    app_db_manager = _AppDbManager()
    finished: list[tuple[bool, str, str | None]] = []

    RestoreJob(
        sqlite_ops=_SqliteOps(live_db, source_backup),
        fsops=_FsOps(),
        app_db_manager=app_db_manager,
    )._run(
        str(source_backup),
        _Callbacks(finished=lambda ok, msg, path: finished.append((ok, msg, path))),
    )

    assert finished
    ok, message, path = finished[0]
    assert ok is False
    assert path is None
    assert "Restore failed." in message
    assert "Rollback restored the safety copy" in message
    assert "reopening the application database connection failed" in message
    assert "Application restart required" in message
    assert RESTORE_RESTART_REQUIRED_MARKER in message
    assert live_db.read_text() == "original"
    assert app_db_manager.close_calls == 2
    assert app_db_manager.open_calls == 2


def test_restore_failure_marker_closes_app_without_showing_marker(monkeypatch):
    controller = BackupRestoreController()
    progress = _ProgressDialog()
    scheduled = []

    class Timer:
        @staticmethod
        def singleShot(delay_ms, callback):
            scheduled.append((delay_ms, callback))

    def quit_app():
        pass

    class CoreApplication:
        quit = staticmethod(quit_app)

    monkeypatch.setattr(controller_module, "QTimer", Timer)
    monkeypatch.setattr(controller_module, "QCoreApplication", CoreApplication)

    controller._on_restore_finished(
        False,
        f"Restore failed.\n\nApplication restart required.\n{RESTORE_RESTART_REQUIRED_MARKER}",
        None,
        progress,
    )

    assert progress.finished == (False, "Restore failed.\n\nApplication restart required.", None)
    assert progress.logs == ["Restore failed.\n\nApplication restart required."]
    assert scheduled == [(0, quit_app)]
