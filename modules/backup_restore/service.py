"""
modules/backup_restore/service.py

Purpose
-------
Orchestrate long-running Backup/Restore tasks off the UI thread and report progress
back to the controller via duck-typed callbacks.

Public interface
----------------
- BackupJob.run_async(dest_file: str, callbacks: ProgressCallbacks) -> None
- RestoreJob.run_async(src_file: str, callbacks: ProgressCallbacks) -> None

Where ProgressCallbacks is any object (or simple namespace) that exposes:
- phase(text: str)
- progress(pct: int)                  # 0..100, or negative for indeterminate
- log(line: str)
- finished(success: bool, message: str, path: Optional[str])
"""

from __future__ import annotations

import logging
import os
import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Slot


# ----------------------------
# Utilities
# ----------------------------

def _safe_call(fn: Optional[Callable], *args, **kwargs) -> None:
    """Call a callback if present; swallow exceptions from UI layer."""
    if fn is None:
        return
    try:
        fn(*args, **kwargs)
    except Exception:
        # We never want UI callback failures to crash the worker.
        pass


def _fmt_err(msg: str, exc: BaseException | None = None) -> str:
    if exc is None:
        return msg
    return f"{msg}\n\n{exc.__class__.__name__}: {exc}"


@dataclass
class _Callbacks:
    phase: Optional[Callable[[str], None]] = None
    progress: Optional[Callable[[int], None]] = None
    log: Optional[Callable[[str], None]] = None
    finished: Optional[Callable[[bool, str, Optional[str]], None]] = None


# ----------------------------
# Base runnable
# ----------------------------

class _JobRunnable(QRunnable):
    """
    Thin QRunnable wrapper that executes a callable and ensures completion
    callbacks always run.
    """
    def __init__(self, work: Callable[[], None]) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._work = work

    @Slot()
    def run(self) -> None:  # type: ignore[override]
        self._work()


# ----------------------------
# Backup Job
# ----------------------------

class BackupJob(QObject):
    """
    Encapsulates the backup workflow and progress reporting.
    """
    def __init__(self, db_locator=None, sqlite_ops=None, fsops=None, logger: Optional[logging.Logger] = None) -> None:
        super().__init__()
        self._db_locator = db_locator  # reserved; not used (sqlite_ops.get_db_path handles it)
        self._sqlite_ops = sqlite_ops
        self._fsops = fsops
        self._pool = QThreadPool.globalInstance()
        self._log = logger or logging.getLogger(__name__)

    def run_async(self, dest_file: str, callbacks) -> None:
        cb = _Callbacks(
            phase=getattr(callbacks, "phase", None),
            progress=getattr(callbacks, "progress", None),
            log=getattr(callbacks, "log", None),
            finished=getattr(callbacks, "finished", None),
        )
        runnable = _JobRunnable(lambda: self._run(dest_file, cb))
        self._pool.start(runnable)

    # ---- core workflow (runs in worker thread) ----
    def _run(self, dest_file: str, cb: _Callbacks) -> None:
        try:
            # Resolve collaborators lazily
            sqlite_ops = self._sqlite_ops or self._import_sqlite_ops()
            fsops = self._fsops or self._import_fsops()

            dest = Path(dest_file)
            dest_parent = dest.parent if dest.parent != Path("") else Path.cwd()
            _safe_call(cb.phase, "Preflight")
            _safe_call(cb.progress, -1)

            # Gather stats
            db_path = Path(sqlite_ops.get_db_path())
            db_size = int(sqlite_ops.get_db_size_bytes(str(db_path)))
            free_bytes = int(fsops.get_free_space_bytes(str(dest_parent)))

            needed = int(db_size * 1.5)
            if free_bytes < needed:
                raise RuntimeError(
                    f"Not enough free space in destination folder.\n"
                    f"Required (approx): {self._human_size(needed)}, Available: {self._human_size(free_bytes)}."
                )

            if not dest_parent.exists():
                raise RuntimeError("Destination folder does not exist.")
            if dest.exists() and dest.is_dir():
                raise RuntimeError("Destination path refers to a directory, not a file.")

            # Snapshot
            _safe_call(cb.phase, "Snapshotting database")
            _safe_call(cb.log, f"Reading from: {db_path}")
            tmp_snapshot = fsops.make_temp_file(suffix=".imsdb", dir=str(dest_parent))

            def step(pct: int) -> None:
                # Clamp to 0..95 during copy phase, leave room for verify/save
                pct = max(0, min(95, pct))
                _safe_call(cb.progress, pct)

            sqlite_ops.create_consistent_snapshot(tmp_snapshot, progress_step=step)

            # Verify snapshot
            _safe_call(cb.phase, "Verifying backup image")
            if not sqlite_ops.quick_check(tmp_snapshot):
                raise RuntimeError("Snapshot integrity check failed (PRAGMA quick_check != 'ok').")
            _safe_call(cb.progress, 97)

            # Save atomically
            _safe_call(cb.phase, "Saving")
            # enforce .imsdb extension
            if dest.suffix.lower() != ".imsdb":
                dest = dest.with_suffix(".imsdb")
            fsops.atomic_move(tmp_snapshot, str(dest))
            _safe_call(cb.progress, 100)
            _safe_call(cb.log, f"Backup written to: {dest}")

            _safe_call(cb.finished, True, "Backup completed successfully.", str(dest))

        except Exception as exc:
            self._log.debug("Backup failed:\n%s", traceback.format_exc())
            _safe_call(cb.finished, False, _fmt_err("Backup failed.", exc), None)

    # ---- helpers ----
    @staticmethod
    def _human_size(num: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(num)
        for u in units:
            if size < 1024.0 or u == units[-1]:
                return f"{size:.1f} {u}"
            size /= 1024.0

    @staticmethod
    def _import_sqlite_ops():
        from . import sqlite_ops  # type: ignore
        return sqlite_ops

    @staticmethod
    def _import_fsops():
        from . import fsops  # type: ignore
        return fsops


# ----------------------------
# Restore Job
# ----------------------------

class RestoreJob(QObject):
    """
    Encapsulates the restore workflow and progress reporting.
    """
    def __init__(
        self,
        db_locator=None,
        sqlite_ops=None,
        fsops=None,
        app_db_manager=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__()
        self._db_locator = db_locator
        self._sqlite_ops = sqlite_ops
        self._fsops = fsops
        self._app_db_manager = app_db_manager
        self._pool = QThreadPool.globalInstance()
        self._log = logger or logging.getLogger(__name__)

    def run_async(self, src_file: str, callbacks) -> None:
        cb = _Callbacks(
            phase=getattr(callbacks, "phase", None),
            progress=getattr(callbacks, "progress", None),
            log=getattr(callbacks, "log", None),
            finished=getattr(callbacks, "finished", None),
        )
        runnable = _JobRunnable(lambda: self._run(src_file, cb))
        self._pool.start(runnable)

    # ---- core workflow (runs in worker thread) ----
    def _run(self, src_file: str, cb: _Callbacks) -> None:
        safety_dir: Optional[str] = None
        swapped: bool = False
        try:
            sqlite_ops = self._sqlite_ops or self._import_sqlite_ops()
            fsops = self._fsops or self._import_fsops()

            imsdb = Path(src_file)
            if not imsdb.exists() or not imsdb.is_file():
                raise RuntimeError("Backup file does not exist.")
            if imsdb.suffix.lower() != ".imsdb":
                raise RuntimeError("Backup file must have .imsdb extension.")

            db_path = Path(sqlite_ops.get_db_path())
            _safe_call(cb.phase, "Validating backup")
            _safe_call(cb.progress, 5)
            if not sqlite_ops.quick_check(str(imsdb)):
                raise RuntimeError("Selected backup failed integrity check (PRAGMA quick_check != 'ok').")

            # Safety copy current DB
            _safe_call(cb.phase, "Creating safety copy")
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            safety_dir = fsops.safety_copy_current_db(str(db_path), ts)
            _safe_call(cb.log, f"Safety copy created at: {safety_dir}")
            _safe_call(cb.progress, 25)

            # Swap files
            _safe_call(cb.phase, "Swapping database files")
            if self._app_db_manager is None:
                raise RuntimeError("No database manager available to coordinate connections.")
            self._app_db_manager.close_all()
            fsops.replace_db_with(str(imsdb), str(db_path))
            swapped = True
            self._app_db_manager.open()
            _safe_call(cb.progress, 70)

            # Post-restore checks
            _safe_call(cb.phase, "Post-restore checks")
            if not sqlite_ops.quick_check(str(db_path)):
                raise RuntimeError("Restored database failed integrity check (PRAGMA quick_check != 'ok').")

            # NEW: Foreign key integrity check (fail if any violations are present)
            _safe_call(cb.phase, "Checking foreign keys")
            violations = self._foreign_key_violations(str(db_path))
            if violations:
                # Show a concise sample to aid debugging
                lines = []
                for v in violations[:10]:
                    if hasattr(v, "keys"):
                        table = v.get("table")
                        rowid = v.get("rowid")
                        parent = v.get("parent")
                        fkid = v.get("fkid")
                    else:
                        # tuple order: table, rowid, parent, fkid
                        table, rowid, parent, fkid = (v + (None, None, None, None))[:4]
                    lines.append(f"- table={table}, rowid={rowid}, parent={parent}, fkid={fkid}")
                detail = "\n".join(lines) if lines else "(no detail rows)"
                raise RuntimeError(
                    f"Foreign key check failed: {len(violations)} violation(s) detected.\n"
                    f"{detail}"
                )

            _safe_call(cb.progress, 100)
            _safe_call(cb.log, "Restore completed successfully.")
            _safe_call(cb.finished, True, "Restore completed successfully.", str(imsdb))

        except Exception as exc:
            self._log.debug("Restore failed:\n%s", traceback.format_exc())
            # Attempt rollback if swap already happened
            if swapped and safety_dir:
                try:
                    _safe_call(cb.log, "Attempting rollback from safety copy…")
                    if self._app_db_manager:
                        self._app_db_manager.close_all()
                    # Safety dir contains original db + possible wal/shm
                    # Find the original DB file name by matching current db_path.name
                    sqlite_ops = self._sqlite_ops or self._import_sqlite_ops()
                    db_path = Path(sqlite_ops.get_db_path())
                    original = Path(safety_dir) / db_path.name
                    if not original.exists():
                        # Fallback: any .db in safety dir
                        candidates = list(Path(safety_dir).glob("*.db"))
                        if candidates:
                            original = candidates[0]
                    fsops = self._fsops or self._import_fsops()
                    fsops.replace_db_with(str(original), str(db_path))
                    if self._app_db_manager:
                        self._app_db_manager.open()
                    _safe_call(cb.log, "Rollback succeeded.")
                except Exception as rollback_exc:
                    self._log.debug("Rollback also failed:\n%s", traceback.format_exc())
                    _safe_call(cb.log, _fmt_err("Rollback failed.", rollback_exc))

            _safe_call(cb.finished, False, _fmt_err("Restore failed.", exc), None)

    @staticmethod
    def _foreign_key_violations(db_path: str) -> list:
        """
        Run PRAGMA foreign_key_check on the given database path and return any violations.
        Each row is (table, rowid, parent, fkid). Empty list means no violations.
        """
        with sqlite3.connect(db_path) as con:
            try:
                con.row_factory = sqlite3.Row
            except Exception:
                pass
            cur = con.execute("PRAGMA foreign_key_check")
            return cur.fetchall()

    @staticmethod
    def _import_sqlite_ops():
        from . import sqlite_ops  # type: ignore
        return sqlite_ops

    @staticmethod
    def _import_fsops():
        from . import fsops  # type: ignore
        return fsops
