"""
modules/backup_restore/sqlite_ops.py

Purpose
-------
SQLite-aware operations for creating a **consistent** database snapshot and performing
lightweight/heavyweight integrity checks. Designed to work with both WAL and non-WAL
modes and to expose progress during backups when available.

Public Interface
----------------
- get_db_path() -> str
- get_db_size_bytes(path: Optional[str] = None) -> int
- is_wal_mode(path: Optional[str] = None) -> bool
- create_consistent_snapshot(dest_path: str, progress_step: Optional[Callable[[int], None]] = None) -> None
- quick_check(db_path: str) -> bool
- integrity_check(db_path: str, limit_errors: int = 3) -> Tuple[bool, List[str]]

Notes
-----
- Prefers the SQLite Online Backup API. Falls back to VACUUM INTO when backup API
  is not available or if the underlying SQLite version lacks features.
- Never copies -wal/-shm files. The snapshot is a single standalone .sqlite file.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

__all__ = [
    "get_db_path",
    "get_db_size_bytes",
    "is_wal_mode",
    "create_consistent_snapshot",
    "quick_check",
    "integrity_check",
    "set_db_path",  # optional helper
]

# ----------------------------
# DB path resolution
# ----------------------------

_DB_PATH: Optional[str] = None  # set via set_db_path() if desired


def set_db_path(path: str) -> None:
    """Optional helper for apps that want to explicitly set the DB path at runtime."""
    global _DB_PATH
    _DB_PATH = str(Path(path).expanduser().resolve())


def _resolve_db_path() -> str:
    """
    Resolve the absolute path of the live application database.

    Resolution order:
      1) Value set via set_db_path()
      2) Environment variable APP_DB_PATH
      3) Optional app-provided helpers:
         - core.db.get_db_path()
         - database.get_db_path()
         - app.database.get_db_path()

    Raise a RuntimeError if none are found.
    """
    if _DB_PATH:
        return _DB_PATH

    env = os.getenv("APP_DB_PATH")
    if env:
        return str(Path(env).expanduser().resolve())

    # Attempt to call well-known helpers if present
    candidates = [
        ("core.db", "get_db_path"),
        ("database", "get_db_path"),
        ("app.database", "get_db_path"),
    ]
    for mod, attr in candidates:
        try:
            m = __import__(mod, fromlist=[attr])
            fn = getattr(m, attr, None)
            if callable(fn):
                path = fn()
                if path:
                    return str(Path(path).expanduser().resolve())
        except Exception:
            # Quietly ignore; we'll fail below if nothing resolves.
            pass

    raise RuntimeError(
        "sqlite_ops.get_db_path(): Unable to resolve DB path. "
        "Call set_db_path(path) at startup or set APP_DB_PATH environment variable, "
        "or expose core.db.get_db_path()."
    )


# ----------------------------
# Basic info helpers
# ----------------------------

def get_db_path() -> str:
    """Return the absolute path to the live database file."""
    return _resolve_db_path()


def get_db_size_bytes(path: Optional[str] = None) -> int:
    """Return the size (bytes) of the given DB (or current app DB if None)."""
    p = Path(path or get_db_path())
    return p.stat().st_size if p.exists() else 0


def _connect_ro(db_path: str) -> sqlite3.Connection:
    """
    Open a read-only connection via URI. This avoids creating -wal/-shm and is
    safe for integrity checks.
    """
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)


def is_wal_mode(path: Optional[str] = None) -> bool:
    """Return True if the database journal mode is WAL."""
    db_path = path or get_db_path()
    with _connect_ro(db_path) as con:
        row = con.execute("PRAGMA journal_mode;").fetchone()
    # sqlite returns ('wal',) or similar
    return (row[0] if row else "").lower() == "wal"


# ----------------------------
# Snapshot (Backup) operations
# ----------------------------

def create_consistent_snapshot(
    dest_path: str,
    progress_step: Optional[Callable[[int], None]] = None,
) -> None:
    """
    Create a consistent snapshot of the live database into `dest_path`.

    Strategy priority:
      1) Online Backup API (Connection.backup), with progress callback.
      2) VACUUM INTO '<dest_path>' as a fallback (requires short exclusive lock).

    The resulting file at `dest_path` is a complete standalone SQLite database.
    """
    src_path = get_db_path()
    dest_path = str(Path(dest_path).with_suffix(".imsdb"))  # ensure extension if omitted

    # Attempt Online Backup API first
    if _try_backup_api(src_path, dest_path, progress_step):
        return

    # Fallback to VACUUM INTO (SQLite >= 3.27). This may require a brief exclusive lock.
    _vacuum_into(src_path, dest_path)
    if progress_step:
        progress_step(100)


def _try_backup_api(
    src_path: str,
    dest_path: str,
    progress_step: Optional[Callable[[int], None]],
) -> bool:
    """
    Use sqlite3's Connection.backup if available. Returns True on success, False if
    unsupported or fails before writing (the caller will fall back to VACUUM INTO).
    """
    try:
        # Open live DB normally (rw), and destination as a new file
        with sqlite3.connect(src_path, isolation_level=None, check_same_thread=False) as src, \
             sqlite3.connect(dest_path, isolation_level=None, check_same_thread=False) as dst:

            # Try to estimate total pages for progress reporting
            # total_pages is provided in the progress callback for Python 3.11+
            # We'll use that if available; otherwise, we keep progress_step best-effort.
            def _progress(status: int, remaining: int, total: int) -> None:
                # status: SQLITE_OK/ERROR, remaining/total pages
                if progress_step and total > 0:
                    done = max(0, total - remaining)
                    pct = int((done / total) * 100)
                    progress_step(min(95, max(0, pct)))  # reserve a little headroom
            # Copy in chunks to allow UI updates
            src.backup(dst, pages=1024, progress=_progress)
        if progress_step:
            progress_step(97)
        return True
    except Exception:
        # Returning False triggers fallback.
        return False


def _vacuum_into(src_path: str, dest_path: str) -> None:
    """
    Use VACUUM INTO to create a compact copy of the database at dest_path.
    Requires SQLite 3.27+. Will hold a short exclusive lock.
    """
    # Ensure destination directory exists
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

    # VACUUM INTO must run on a connection to the source DB
    with sqlite3.connect(src_path, isolation_level=None, check_same_thread=False) as con:
        # Ensure no pending transaction
        con.execute("PRAGMA wal_checkpoint(PASSIVE);")
        # Surround with a try to provide clearer error if SQLite is too old
        try:
            con.execute(f"VACUUM INTO '{dest_path}';")
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "VACUUM INTO is not supported by the linked SQLite library. "
                "Consider upgrading Python/SQLite, or ensure the Online Backup API is available."
            ) from exc


# ----------------------------
# Integrity checks
# ----------------------------

def quick_check(db_path: str) -> bool:
    """
    Run PRAGMA quick_check; returns True iff result is exactly 'ok'.
    """
    p = Path(db_path)
    if not p.exists() or not p.is_file():
        return False
    try:
        with _connect_ro(str(p)) as con:
            row = con.execute("PRAGMA quick_check;").fetchone()
        return (row and isinstance(row[0], str) and row[0].lower() == "ok")
    except Exception:
        return False


def integrity_check(db_path: str, limit_errors: int = 3) -> Tuple[bool, List[str]]:
    """
    Run PRAGMA integrity_check and return (ok, errors). If not ok, returns up to
    `limit_errors` sample error lines for diagnostics.
    """
    errors: List[str] = []
    try:
        with _connect_ro(db_path) as con:
            # integrity_check can return many rows; collect a few
            for row in con.execute("PRAGMA integrity_check;"):
                val = row[0] if row else ""
                if isinstance(val, str) and val.lower() == "ok":
                    # If it's a single 'ok', we consider DB healthy
                    return True, []
                # Otherwise, accumulate errors (avoid duplicates)
                if isinstance(val, str):
                    errors.append(val)
                    if len(errors) >= max(1, limit_errors):
                        break
    except Exception as exc:
        errors.append(f"exception: {exc!r}")

    return (len(errors) == 0), errors
