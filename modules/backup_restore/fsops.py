"""
modules/backup_restore/fsops.py

Purpose
-------
File-system utilities with attention to atomicity and cross-platform behavior.

Public interface
----------------
- ensure_writable_dir(path: str) -> None
- get_free_space_bytes(path: str) -> int
- atomic_move(src: str, dest: str) -> None
- make_temp_file(suffix: str = "", dir: Optional[str] = None) -> str
- safety_copy_current_db(db_path: str, timestamp: str) -> str
- replace_db_with(source_db_file: str, target_db_path: str) -> None
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

__all__ = [
    "ensure_writable_dir",
    "get_free_space_bytes",
    "atomic_move",
    "make_temp_file",
    "safety_copy_current_db",
    "replace_db_with",
]

# ----------------------------
# Helpers (private)
# ----------------------------

def _fsync_file(path: Path) -> None:
    """Best-effort fsync for a file."""
    try:
        fd = os.open(str(path), os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        # Best-effort; ignore on systems that don't expose fsync or RO files.
        pass


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync for a directory (important after rename/replace)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass


def _copy_file_fsync(src: Path, dst: Path) -> None:
    """Copy file bytes+metadata and fsync the destination."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    _fsync_file(dst)


def _same_device(p1: Path, p2: Path) -> bool:
    """Return True if two paths live on the same device/volume (best-effort)."""
    try:
        return p1.resolve().anchor == p2.resolve().anchor or p1.stat().st_dev == p2.stat().st_dev
    except Exception:
        # Fall back to anchor comparison (Windows drive letter); good enough for deciding strategy.
        return p1.resolve().anchor == p2.resolve().anchor


# ----------------------------
# Public API
# ----------------------------

def ensure_writable_dir(path: str) -> None:
    """
    Validate that `path` exists, is a directory, and is writable/executable.
    Raise RuntimeError with a helpful message if not.
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError(f"Destination folder does not exist: {p}")
    if not p.is_dir():
        raise RuntimeError(f"Destination path is not a folder: {p}")
    if not os.access(str(p), os.W_OK | os.X_OK):
        raise RuntimeError(f"Destination folder is not writable: {p}")

    # Try creating a tiny temp file to verify actual write perms
    try:
        tmp = tempfile.NamedTemporaryFile(prefix=".permcheck_", dir=str(p), delete=True)
        tmp.close()
    except Exception as exc:
        raise RuntimeError(f"Unable to write to destination folder: {p} ({exc})") from exc


def get_free_space_bytes(path: str) -> int:
    """
    Return available free space in bytes for the filesystem that contains `path`.
    """
    probe = Path(path)
    if not probe.exists():
        probe = probe.parent if probe.parent.exists() else Path.home()
    usage = shutil.disk_usage(str(probe))
    return int(usage.free)


def make_temp_file(suffix: str = "", dir: Optional[str] = None) -> str:
    """
    Create a NamedTemporaryFile on disk that persists after close (delete=False),
    returning its absolute path. Caller is responsible for cleanup or moving.
    """
    d = Path(dir) if dir else Path(tempfile.gettempdir())
    d.mkdir(parents=True, exist_ok=True)
    f = tempfile.NamedTemporaryFile(prefix="ims_", suffix=suffix, dir=str(d), delete=False)
    f_path = Path(f.name).resolve()
    f.close()
    return str(f_path)


def atomic_move(src: str, dest: str) -> None:
    """
    Atomically move `src` to `dest` if possible. If across volumes, perform a
    copy+fsync into a temporary file next to `dest` and then os.replace().
    """
    src_p = Path(src).resolve()
    dest_p = Path(dest).resolve()
    dest_p.parent.mkdir(parents=True, exist_ok=True)

    if _same_device(src_p, dest_p):
        # Same volume: os.replace is atomic
        # Ensure destination tmp is not colliding
        tmp_dest = dest_p.with_suffix(dest_p.suffix + ".tmp")
        if tmp_dest.exists():
            tmp_dest.unlink(missing_ok=True)
        # Move to tmp then replace final (gives a more consistent state if something interrupts)
        shutil.move(str(src_p), str(tmp_dest))
        _fsync_file(tmp_dest)
        os.replace(str(tmp_dest), str(dest_p))
        _fsync_dir(dest_p.parent)
        return

    # Cross-volume: copy → fsync → replace
    tmp_dest = dest_p.with_suffix(dest_p.suffix + ".part")
    if tmp_dest.exists():
        tmp_dest.unlink(missing_ok=True)
    _copy_file_fsync(src_p, tmp_dest)
    os.replace(str(tmp_dest), str(dest_p))
    _fsync_dir(dest_p.parent)
    # Remove source best-effort
    try:
        src_p.unlink(missing_ok=True)
    except Exception:
        pass


def safety_copy_current_db(db_path: str, timestamp: str) -> str:
    """
    Create a safety copy folder adjacent to the DB file:
      <db_dir>/pre-restore-<timestamp>/
    Copy the DB file and its -wal/-shm companions if present.
    Return the safety folder path.
    """
    db = Path(db_path).resolve()
    if not db.exists():
        raise RuntimeError(f"Database file not found for safety copy: {db}")
    out_dir = db.parent / f"pre-restore-{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Core DB file
    _copy_file_fsync(db, out_dir / db.name)

    # Companion files (WAL/SHM)
    for suffix in ("-wal", "-shm"):
        comp = Path(str(db) + suffix)
        if comp.exists() and comp.is_file():
            _copy_file_fsync(comp, out_dir / comp.name)

    _fsync_dir(out_dir)
    return str(out_dir.resolve())


def replace_db_with(source_db_file: str, target_db_path: str) -> None:
    """
    Replace the live DB file with `source_db_file` safely.

    Steps:
      - Ensure target directory exists.
      - Remove lingering target -wal/-shm files, if any.
      - Copy source to a temp file in the target directory and fsync.
      - os.replace() temp → target (atomic on same volume).
      - fsync target directory.
    """
    src = Path(source_db_file).resolve()
    tgt = Path(target_db_path).resolve()
    if not src.exists() or not src.is_file():
        raise RuntimeError(f"Source DB file not found: {src}")

    tgt.parent.mkdir(parents=True, exist_ok=True)

    # Remove any stale WAL/SHM for the target DB
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(tgt) + suffix) if suffix else tgt
        if stale.exists():
            try:
                stale.unlink()
            except Exception:
                # If removing the main DB fails due to permissions/locks, propagate a clearer error
                if suffix == "":
                    raise RuntimeError(
                        f"Unable to remove current database file (is it locked?): {stale}"
                    )
                # For wal/shm, continue best-effort

    # Copy into a temporary file in the *target* directory to ensure atomic rename
    tmp = tgt.with_suffix(tgt.suffix + ".swap")
    if tmp.exists():
        tmp.unlink(missing_ok=True)
    _copy_file_fsync(src, tmp)

    # Atomic replace
    os.replace(str(tmp), str(tgt))
    _fsync_dir(tgt.parent)
