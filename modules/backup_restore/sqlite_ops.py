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
- get_journal_mode(path: Optional[str] = None) -> str
- create_consistent_snapshot(
      dest_path: str,
      progress_step: Optional[Callable[[int], None]] = None,
      log: Optional[Callable[[str], None]] = None,
      verify_mode: Optional[str] = None,           # 'quick' (default behavior if None), 'integrity'
      fk_check: bool = False,
      limit_errors: int = 3
  ) -> None
- quick_check(db_path: str) -> bool
- integrity_check(db_path: str, limit_errors: int = 3) -> Tuple[bool, List[str]]
- foreign_key_check(db_path: str) -> List[sqlite3.Row]
- verify_database(db_path: str, mode: str = "quick", fk_check: bool = False, limit_errors: int = 3) -> Tuple[bool, List[str]]

Notes
-----
- Prefers the SQLite Online Backup API. Falls back to VACUUM INTO when backup API
  is not available or if the underlying SQLite version lacks features.
- Never copies -wal/-shm files. The snapshot is a single standalone .sqlite file.
- New optional operability features:
    * Logs the current journal_mode (WAL/DELETE/etc.) at snapshot time if a log callback is provided.
    * Optional post-snapshot verification: 'quick' (PRAGMA quick_check) or 'integrity'
      (PRAGMA integrity_check) and optional PRAGMA foreign_key_check. Disabled by default
      to preserve prior behavior/perf.
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
    "get_journal_mode",
    "create_consistent_snapshot",
    "quick_check",
    "integrity_check",
    "foreign_key_check",
    "verify_database",
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
    con = sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def is_wal_mode(path: Optional[str] = None) -> bool:
    """Return True if the database journal mode is WAL."""
    return get_journal_mode(path).lower() == "wal"


def get_journal_mode(path: Optional[str] = None) -> str:
    """Return the current journal_mode string (e.g., 'wal', 'delete', 'off')."""
    db_path = path or get_db_path()
    with _connect_ro(db_path) as con:
        row = con.execute("PRAGMA journal_mode;").fetchone()
    return (row[0] if row else "") or ""


# ----------------------------
# Snapshot (Backup) operations
# ----------------------------

def create_consistent_snapshot(
    dest_path: str,
    progress_step: Optional[Callable[[int], None]] = None,
    log: Optional[Callable[[str], None]] = None,
    verify_mode: Optional[str] = None,  # None (default, no verify), 'quick', or 'integrity'
    fk_check: bool = False,
    limit_errors: int = 3,
) -> None:
    """
    Create a consistent snapshot of the live database into `dest_path`.

    Strategy priority:
      1) Online Backup API (Connection.backup), with progress callback.
      2) VACUUM INTO '<dest_path>' as a fallback (requires short exclusive lock).

    The resulting file at `dest_path` is a complete standalone SQLite database.

    Operability/diagnostics:
      - If `log` is provided, logs journal_mode at start and verification steps/results.
      - If `verify_mode` is provided:
          * 'quick'     -> PRAGMA quick_check; raise on failure
          * 'integrity' -> PRAGMA integrity_check (slower); raise on failure (up to `limit_errors` details)
      - If `fk_check` is True, runs PRAGMA foreign_key_check and raises on any violations.
    """
    src_path = get_db_path()
    # ensure extension if omitted, but preserve caller's provided suffix if already .imsdb
    dest_path = str(Path(dest_path).with_suffix(".imsdb"))

    # Log journal mode (if requested)
    try:
        jm = get_journal_mode(src_path)
        if log:
            log(f"Journal mode: {jm.upper() or '(unknown)'}")
    except Exception:
        # Best-effort diagnostics; don't fail snapshot if this query fails.
        pass

    # Attempt Online Backup API first
    if _try_backup_api(src_path, dest_path, progress_step):
        if progress_step:
            progress_step(97)
    else:
        # Fallback to VACUUM INTO (SQLite >= 3.27). This may require a brief exclusive lock.
        _vacuum_into(src_path, dest_path)
        if progress_step:
            progress_step(100)

    # Optional verification on the produced snapshot
    if verify_mode:
        mode = (verify_mode or "").strip().lower()
        if log:
            log(f"Verifying snapshot using: {mode}{' + FK check' if fk_check else ''}")
        ok, details = verify_database(dest_path, mode=mode, fk_check=fk_check, limit_errors=limit_errors)
        if not ok:
            # Include a few diagnostic lines
            snippet = "\n".join(details[:max(1, limit_errors)]) if details else "(no details)"
            raise RuntimeError(f"Snapshot verification failed [{mode}]:\n{snippet}")
        if log:
            log("Verification passed.")

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
            src.row_factory = sqlite3.Row
            dst.row_factory = sqlite3.Row

            # total_pages is provided in the progress callback for Python 3.11+
            def _progress(status: int, remaining: int, total: int) -> None:
                if progress_step and total > 0:
                    done = max(0, total - remaining)
                    pct = int((done / total) * 100)
                    progress_step(min(95, max(0, pct)))  # reserve a little headroom
            # Copy in chunks to allow UI updates
            src.backup(dst, pages=1024, progress=_progress)
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
        con.row_factory = sqlite3.Row
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


def foreign_key_check(db_path: str) -> List[sqlite3.Row]:
    """
    Run PRAGMA foreign_key_check and return any violations.
    Each row has columns: table, rowid, parent, fkid. Empty list => no violations.
    """
    p = Path(db_path)
    if not p.exists() or not p.is_file():
        return []
    try:
        with _connect_ro(str(p)) as con:
            cur = con.execute("PRAGMA foreign_key_check;")
            return cur.fetchall()
    except Exception:
        return []


def verify_database(
    db_path: str,
    mode: str = "quick",
    fk_check: bool = False,
    limit_errors: int = 3,
) -> Tuple[bool, List[str]]:
    """
    Unified verification helper.

    Args:
        db_path: Path to the database to verify.
        mode: 'quick' (PRAGMA quick_check) or 'integrity' (PRAGMA integrity_check).
        fk_check: If True, also run PRAGMA foreign_key_check and include a summary if violations exist.
        limit_errors: Max number of integrity_check error messages to return.

    Returns:
        (ok, details) where `ok` is True iff all requested checks passed.
        `details` contains a small set of human-readable strings when failures occur.
    """
    mode = (mode or "quick").strip().lower()
    details: List[str] = []

    ok = True
    if mode == "integrity":
        ok_int, errs = integrity_check(db_path, limit_errors=limit_errors)
        ok = ok and ok_int
        if not ok_int:
            details.append("integrity_check failed:")
            details.extend(errs)
    elif mode == "quick":
        if not quick_check(db_path):
            ok = False
            details.append("quick_check failed (result != 'ok').")
    else:
        details.append(f"Unknown verify mode: {mode!r}. Expected 'quick' or 'integrity'.")
        ok = False

    if fk_check:
        fkv = foreign_key_check(db_path)
        if fkv:
            ok = False
            details.append(f"foreign_key_check violations: {len(fkv)}")
            # include a few for readability
            for r in fkv[:min(5, len(fkv))]:
                if hasattr(r, "keys"):
                    details.append(
                        f"- table={r.get('table')}, rowid={r.get('rowid')}, parent={r.get('parent')}, fkid={r.get('fkid')}"
                    )
                else:
                    t, rowid, parent, fkid = (r + (None, None, None, None))[:4]
                    details.append(f"- table={t}, rowid={rowid}, parent={parent}, fkid={fkid}")

    return ok, details
