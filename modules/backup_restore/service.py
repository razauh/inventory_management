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

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot


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


def _active_db_family(db_path: Path) -> tuple[Path, Path, Path]:
    db_path = db_path.resolve()
    return (db_path, Path(str(db_path) + "-wal").resolve(), Path(str(db_path) + "-shm").resolve())


def _backup_destination(dest: Path) -> Path:
    if dest.name and dest.suffix.lower() != ".imsdb":
        return dest.with_suffix(".imsdb")
    return dest


def _reject_active_db_destination(dest: Path, db_path: Path, *alternates: Path) -> None:
    active_family = _active_db_family(db_path)
    if dest.resolve() in active_family or any(path.resolve() in active_family for path in alternates):
        raise RuntimeError("Backup destination must not be the active database or its WAL/SHM files.")


@dataclass
class _Callbacks:
    phase: Optional[Callable[[str], None]] = None
    progress: Optional[Callable[[int], None]] = None
    log: Optional[Callable[[str], None]] = None
    finished: Optional[Callable[[bool, str, Optional[str]], None]] = None


_ACTIVE_CALLBACK_BRIDGES: list["_CallbackBridge"] = []


class _CallbackBridge(QObject):
    phase_requested = Signal(str)
    progress_requested = Signal(int)
    log_requested = Signal(str)
    finished_requested = Signal(bool, str, object)
    completed = Signal(object)

    def __init__(self, callbacks) -> None:
        super().__init__()
        self._callbacks = _Callbacks(
            phase=getattr(callbacks, "phase", None),
            progress=getattr(callbacks, "progress", None),
            log=getattr(callbacks, "log", None),
            finished=getattr(callbacks, "finished", None),
        )
        self.phase_requested.connect(self._dispatch_phase, Qt.ConnectionType.QueuedConnection)
        self.progress_requested.connect(self._dispatch_progress, Qt.ConnectionType.QueuedConnection)
        self.log_requested.connect(self._dispatch_log, Qt.ConnectionType.QueuedConnection)
        self.finished_requested.connect(self._dispatch_finished, Qt.ConnectionType.QueuedConnection)

    @Slot(str)
    def _dispatch_phase(self, text: str) -> None:
        _safe_call(self._callbacks.phase, text)

    @Slot(int)
    def _dispatch_progress(self, pct: int) -> None:
        _safe_call(self._callbacks.progress, pct)

    @Slot(str)
    def _dispatch_log(self, line: str) -> None:
        _safe_call(self._callbacks.log, line)

    @Slot(bool, str, object)
    def _dispatch_finished(self, success: bool, message: str, path: Optional[str]) -> None:
        _safe_call(self._callbacks.finished, success, message, path)
        self.completed.emit(self)

    def callbacks(self) -> _Callbacks:
        return _Callbacks(
            phase=self.phase_requested.emit,
            progress=self.progress_requested.emit,
            log=self.log_requested.emit,
            finished=self.finished_requested.emit,
        )


def _queued_callbacks(callbacks) -> _Callbacks:
    bridge = _CallbackBridge(callbacks)
    _ACTIVE_CALLBACK_BRIDGES.append(bridge)
    bridge.completed.connect(_release_callback_bridge)
    return bridge.callbacks()


def _release_callback_bridge(bridge: object) -> None:
    try:
        _ACTIVE_CALLBACK_BRIDGES.remove(bridge)  # type: ignore[arg-type]
    except ValueError:
        pass


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
        cb = _queued_callbacks(callbacks)
        runnable = _JobRunnable(lambda: self._run(dest_file, cb))
        self._pool.start(runnable)

    # ---- core workflow (runs in worker thread) ----
    def _run(self, dest_file: str, cb: _Callbacks) -> None:
        tmp_snapshot: Optional[str] = None
        try:
            # Resolve collaborators lazily
            sqlite_ops = self._sqlite_ops or self._import_sqlite_ops()
            fsops = self._fsops or self._import_fsops()

            raw_dest = Path(dest_file)
            dest = _backup_destination(raw_dest)
            dest_parent = dest.parent if dest.parent != Path("") else Path.cwd()
            _safe_call(cb.phase, "Preflight")
            _safe_call(cb.progress, -1)

            # Gather stats
            db_path = Path(sqlite_ops.get_db_path())
            _reject_active_db_destination(dest, db_path, raw_dest)
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

            # Snapshot (uses WAL checkpoint + Online Backup API inside sqlite_ops)
            _safe_call(cb.phase, "Snapshotting database")
            _safe_call(cb.log, f"Reading from: {db_path}")
            tmp_snapshot = fsops.make_temp_file(suffix=".imsdb", dir=str(dest_parent))

            _safe_call(cb.log, "Checkpointing WAL and performing online backup…")
            sqlite_ops.create_consistent_snapshot(
                tmp_snapshot,
                progress_step=cb.progress,
                log=cb.log,
                verify_mode="quick",
            )
            _safe_call(cb.progress, 95)

            # Verify snapshot
            _safe_call(cb.phase, "Verifying backup image")
            if not sqlite_ops.quick_check(tmp_snapshot):
                raise RuntimeError("Snapshot integrity check failed (PRAGMA quick_check != 'ok').")
            _safe_call(cb.progress, 97)

            # Save atomically
            _safe_call(cb.phase, "Saving")
            fsops.atomic_move(tmp_snapshot, str(dest))
            _safe_call(cb.progress, 100)
            _safe_call(cb.log, f"Backup written to: {dest}")

            _safe_call(cb.finished, True, "Backup completed successfully.", str(dest))

        except Exception as exc:
            self._log.debug("Backup failed:\n%s", traceback.format_exc())
            _safe_call(cb.finished, False, _fmt_err("Backup failed.", exc), None)
        finally:
            if tmp_snapshot:
                try:
                    Path(tmp_snapshot).unlink(missing_ok=True)
                except Exception:
                    self._log.debug("Unable to remove temporary backup snapshot: %s", tmp_snapshot, exc_info=True)

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
        cb = _queued_callbacks(callbacks)
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
            if imsdb.resolve() in _active_db_family(db_path):
                raise RuntimeError("Backup file must not be the active database or its WAL/SHM files.")
            _safe_call(cb.phase, "Validating backup")
            _safe_call(cb.progress, 5)
            if not sqlite_ops.quick_check(str(imsdb)):
                raise RuntimeError("Selected backup failed integrity check (PRAGMA quick_check != 'ok').")
            ok_schema, schema_details = sqlite_ops.verify_app_schema_compatibility(str(imsdb))
            if not ok_schema:
                detail = "\n".join(schema_details[:10]) if schema_details else "(no details)"
                raise RuntimeError(
                    "Selected backup is not compatible with this application schema.\n"
                    f"{detail}"
                )

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
