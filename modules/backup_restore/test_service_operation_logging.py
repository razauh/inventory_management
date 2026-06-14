from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

from modules.backup_restore import service
from modules.backup_restore.service import BackupJob, RestoreJob, _Callbacks


class _SqliteOps:
    def __init__(self, live_db: Path) -> None:
        self.live_db = live_db

    def get_db_path(self) -> str:
        return str(self.live_db)

    def get_db_size_bytes(self, path: str) -> int:
        return Path(path).stat().st_size

    def create_consistent_snapshot(
        self,
        dest_path: str,
        progress_step=None,
        log=None,
        verify_mode=None,
    ) -> None:
        shutil.copy2(self.live_db, dest_path)
        if progress_step:
            progress_step(50)
        if log:
            log("snapshot created")

    def quick_check(self, db_path: str) -> bool:
        con = sqlite3.connect(db_path)
        try:
            cur = con.cursor()
            try:
                row = cur.execute("PRAGMA quick_check;").fetchone()
            finally:
                cur.close()
        finally:
            con.close()
        return bool(row and row[0] == "ok")

    def verify_app_schema_compatibility(self, db_path: str) -> tuple[bool, list[str]]:
        return True, []


class _FsOps:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    def get_free_space_bytes(self, path: str) -> int:
        return 1024 * 1024 * 1024

    def make_temp_file(self, suffix: str = "", dir: str | None = None) -> str:
        tmp_file = self.tmp_path / f"snapshot{suffix}"
        tmp_file.touch()
        return str(tmp_file)

    def atomic_move(self, src: str, dest: str) -> None:
        shutil.move(src, dest)

    def safety_copy_current_db(self, db_path: str, timestamp: str) -> str:
        safety_dir = self.tmp_path / f"pre-restore-{timestamp}"
        safety_dir.mkdir()
        shutil.copy2(db_path, safety_dir / Path(db_path).name)
        return str(safety_dir)

    def replace_db_with(self, source_db_file: str, target_db_path: str) -> None:
        shutil.copy2(source_db_file, target_db_path)


class _AppDbManager:
    def __init__(self) -> None:
        self.closed = False
        self.opened = False

    def close_all(self) -> None:
        self.closed = True

    def open(self) -> None:
        self.opened = True


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA foreign_keys = ON;")
        con.execute("CREATE TABLE product(id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
        con.execute("INSERT INTO product(name) VALUES ('Widget');")
        con.commit()
    finally:
        con.close()


def test_backup_job_uses_backup_restore_logger_and_structured_events(monkeypatch, tmp_path):
    live_db = tmp_path / "live.db"
    _make_db(live_db)
    sqlite_ops = _SqliteOps(live_db)
    fsops = _FsOps(tmp_path)
    dest = tmp_path / "backup.imsdb"
    logger = logging.getLogger("test.backup_restore.backup")
    events: list[tuple[str, str, str]] = []

    monkeypatch.setattr(service, "get_logger", lambda: logger)
    monkeypatch.setattr(
        service,
        "log_event",
        lambda logger, op, phase, message, extra=None, level=logging.INFO: events.append((op, phase, message)),
    )

    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(finished=lambda ok, msg, path: finished.append((ok, msg, path)))

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(dest), callbacks)

    assert finished == [(True, "Backup completed successfully.", str(dest))]
    assert [phase for op, phase, _ in events if op == "backup"] == [
        "start",
        "validation",
        "snapshot",
        "verification",
        "save",
        "completion",
    ]


def test_backup_job_logs_failure_event(monkeypatch, tmp_path):
    live_db = tmp_path / "live.imsdb"
    _make_db(live_db)
    sqlite_ops = _SqliteOps(live_db)
    fsops = _FsOps(tmp_path)
    logger = logging.getLogger("test.backup_restore.backup_failure")
    events: list[tuple[str, str, str]] = []

    monkeypatch.setattr(service, "get_logger", lambda: logger)
    monkeypatch.setattr(
        service,
        "log_event",
        lambda logger, op, phase, message, extra=None, level=logging.INFO: events.append((op, phase, message)),
    )

    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(finished=lambda ok, msg, path: finished.append((ok, msg, path)))

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(live_db), callbacks)

    assert len(finished) == 1
    assert finished[0][0] is False
    assert "active database" in finished[0][1]
    assert [phase for op, phase, _ in events if op == "backup"] == ["start", "failure"]


def test_restore_job_logs_validation_safety_swap_verification_and_completion(monkeypatch, tmp_path):
    live_db = tmp_path / "live.db"
    backup_db = tmp_path / "backup.imsdb"
    _make_db(live_db)
    _make_db(backup_db)
    sqlite_ops = _SqliteOps(live_db)
    fsops = _FsOps(tmp_path)
    app_db_manager = _AppDbManager()
    logger = logging.getLogger("test.backup_restore.restore")
    events: list[tuple[str, str, str]] = []

    monkeypatch.setattr(service, "get_logger", lambda: logger)
    monkeypatch.setattr(
        service,
        "log_event",
        lambda logger, op, phase, message, extra=None, level=logging.INFO: events.append((op, phase, message)),
    )

    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(finished=lambda ok, msg, path: finished.append((ok, msg, path)))

    RestoreJob(
        sqlite_ops=sqlite_ops,
        fsops=fsops,
        app_db_manager=app_db_manager,
    )._run(str(backup_db), callbacks)

    assert finished == [(True, "Restore completed successfully.", str(backup_db))]
    assert app_db_manager.closed is True
    assert app_db_manager.opened is True
    assert [phase for op, phase, _ in events if op == "restore"] == [
        "start",
        "validation",
        "safety_copy",
        "safety_copy",
        "swap",
        "swap",
        "verification",
        "verification",
        "completion",
    ]
