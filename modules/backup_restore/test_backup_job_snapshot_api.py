from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from modules.backup_restore.service import BackupJob, _Callbacks


class _SqliteOpsWithoutSnapshot:
    def __init__(self, source_db: Path) -> None:
        self.source_db = source_db
        self.snapshot_calls: list[tuple[str, object, object, str | None]] = []

    def get_db_path(self) -> str:
        return str(self.source_db)

    def get_db_size_bytes(self, path: str) -> int:
        return Path(path).stat().st_size

    def create_consistent_snapshot(
        self,
        dest_path: str,
        progress_step=None,
        log=None,
        verify_mode=None,
    ) -> None:
        self.snapshot_calls.append((dest_path, progress_step, log, verify_mode))
        shutil.copy2(self.source_db, dest_path)
        if progress_step:
            progress_step(42)
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


def test_backup_job_uses_create_consistent_snapshot_without_snapshot_api(tmp_path):
    source_db = tmp_path / "live.sqlite"
    con = sqlite3.connect(source_db)
    try:
        con.execute("CREATE TABLE product(id INTEGER PRIMARY KEY, name TEXT NOT NULL);")
        con.execute("INSERT INTO product(name) VALUES ('Widget');")
        con.commit()
    finally:
        con.close()

    sqlite_ops = _SqliteOpsWithoutSnapshot(source_db)
    fsops = _FsOps(tmp_path)
    dest = tmp_path / "backup.imsdb"
    progress_values: list[int] = []
    log_lines: list[str] = []
    finished: list[tuple[bool, str, str | None]] = []

    callbacks = _Callbacks(
        progress=progress_values.append,
        log=log_lines.append,
        finished=lambda ok, msg, path: finished.append((ok, msg, path)),
    )

    BackupJob(sqlite_ops=sqlite_ops, fsops=fsops)._run(str(dest), callbacks)

    assert finished == [(True, "Backup completed successfully.", str(dest))]
    assert dest.exists()
    assert sqlite_ops.snapshot_calls
    snapshot_path, progress_cb, log_cb, verify_mode = sqlite_ops.snapshot_calls[0]
    assert Path(snapshot_path).suffix == ".imsdb"
    assert progress_cb is callbacks.progress
    assert log_cb is callbacks.log
    assert verify_mode == "quick"
    assert 42 in progress_values
    assert "snapshot created" in log_lines

    con = sqlite3.connect(dest)
    try:
        row = con.execute("SELECT name FROM product WHERE id = 1;").fetchone()
    finally:
        con.close()
    assert row == ("Widget",)
