from __future__ import annotations

import sqlite3
from pathlib import Path

from constants import SCHEMA_VERSION
from database.schema import REQUIRED_TABLES
from inventory_management.modules.backup_restore import sqlite_ops
from inventory_management.modules.backup_restore.service import RestoreJob, _Callbacks


def _create_shell_app_db(path: Path, version: str = SCHEMA_VERSION) -> None:
    with sqlite3.connect(path) as con:
        for table in REQUIRED_TABLES:
            con.execute(f"CREATE TABLE {table}(id INTEGER PRIMARY KEY);")
        con.execute(
            """
            CREATE TABLE schema_meta(
                id INTEGER PRIMARY KEY CHECK (id=1),
                version TEXT NOT NULL
            );
            """
        )
        con.execute(
            "INSERT INTO schema_meta(id, version) VALUES (1, ?);",
            (version,),
        )
        con.commit()


class _SqliteOps:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def get_db_path(self) -> str:
        return str(self._db_path)

    def quick_check(self, db_path: str) -> bool:
        return sqlite_ops.quick_check(db_path)

    def verify_app_schema_compatibility(self, db_path: str):
        return sqlite_ops.verify_app_schema_compatibility(db_path)


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


def test_schema_compatibility_rejects_valid_sqlite_file_without_app_schema(tmp_path):
    candidate = tmp_path / "other_app.imsdb"
    with sqlite3.connect(candidate) as con:
        con.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY);")

    ok, details = sqlite_ops.verify_app_schema_compatibility(str(candidate))

    assert ok is False
    assert any("missing required application table" in detail for detail in details)


def test_schema_compatibility_rejects_wrong_schema_version(tmp_path):
    candidate = tmp_path / "old_app.imsdb"
    _create_shell_app_db(candidate, version="v0")

    ok, details = sqlite_ops.verify_app_schema_compatibility(str(candidate))

    assert ok is False
    assert any("unsupported schema version" in detail for detail in details)


def test_restore_rejects_incompatible_backup_before_safety_copy_or_swap(tmp_path):
    live_db = tmp_path / "live.db"
    _create_shell_app_db(live_db)
    candidate = tmp_path / "other_app.imsdb"
    with sqlite3.connect(candidate) as con:
        con.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY);")

    fsops = _FsOps()
    app_db_manager = _AppDbManager()
    finished: list[tuple[bool, str, str | None]] = []
    callbacks = _Callbacks(
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    RestoreJob(
        sqlite_ops=_SqliteOps(live_db),
        fsops=fsops,
        app_db_manager=app_db_manager,
    )._run(str(candidate), callbacks)

    assert finished
    ok, message, path = finished[0]
    assert ok is False
    assert path is None
    assert "not compatible with this application schema" in message
    assert fsops.safety_copy_called is False
    assert fsops.replace_called is False
    assert app_db_manager.close_called is False
    assert app_db_manager.open_called is False
