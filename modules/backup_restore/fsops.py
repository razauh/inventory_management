"""
modules/backup_restore/fsops.py

Purpose
-------
File-system utilities with attention to atomicity and cross-platform behavior.

Public interface
----------------
- ensure_writable_dir(path: str) -> None
- get_free_space_bytes(path: str) -> int
- atomic_move(src: str, dest: str, *, verbose: bool = False, logger: Optional[logging.Logger] = None, strict_verify: bool = False) -> None
- make_temp_file(suffix: str = "", dir: Optional[str] = None) -> str
- safety_copy_current_db(db_path: str, timestamp: str, *, verbose: bool = False, logger: Optional[logging.Logger] = None) -> str
- replace_db_with(source_db_file: str, target_db_path: str, *, verbose: bool = False, logger: Optional[logging.Logger] = None, strict_verify: bool = False) -> None

Notes
-----
- The added `verbose`/`logger` flags emit lightweight, structured logs for swap steps
  (source → temp → final) with byte sizes and timestamps.
- When `strict_verify=True`, a SHA-256 checksum of the produced file is computed and logged.
- All new parameters are optional and keyword-only; existing callers continue to work unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
from datetime import datetime
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

def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _log(logger: Optional[logging.Logger], verbose: bool, message: str, **fields) -> None:
    """Emit a single line of key=value fields if verbose logging is enabled."""
    if not (verbose and logger):
        return
    parts = [message]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    logger.info(" ".join(parts))


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 of a file (streamed)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


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


def atomic_move(
    src: str,
    dest: str,
    *,
    verbose: bool = False,
    logger: Optional[logging.Logger] = None,
    strict_verify: bool = False,
) -> None:
    """
    Atomically move `src` to `dest` if possible. If across volumes, perform a
    copy+fsync into a temporary file next to `dest` and then os.replace().

    Added operability (optional):
      - verbose/logger: emits structured logs for each step with sizes and timestamps.
      - strict_verify: computes SHA-256 of final `dest` and logs it.
    """
    src_p = Path(src).resolve()
    dest_p = Path(dest).resolve()
    dest_p.parent.mkdir(parents=True, exist_ok=True)

    size_src = src_p.stat().st_size if src_p.exists() else 0
    _log(logger, verbose, "atomic_move.start", ts=_now_iso(), src=str(src_p), dest=str(dest_p), src_size=size_src)

    if _same_device(src_p, dest_p):
        # Same volume: os.replace is atomic
        tmp_dest = dest_p.with_suffix(dest_p.suffix + ".tmp")
        if tmp_dest.exists():
            tmp_dest.unlink(missing_ok=True)
        shutil.move(str(src_p), str(tmp_dest))
        _fsync_file(tmp_dest)
        _log(logger, verbose, "atomic_move.to_tmp", ts=_now_iso(), tmp=str(tmp_dest), tmp_size=tmp_dest.stat().st_size)
        os.replace(str(tmp_dest), str(dest_p))
        _fsync_dir(dest_p.parent)
        _log(logger, verbose, "atomic_move.replaced", ts=_now_iso(), final=str(dest_p), final_size=dest_p.stat().st_size)
    else:
        # Cross-volume: copy → fsync → replace
        tmp_dest = dest_p.with_suffix(dest_p.suffix + ".part")
        if tmp_dest.exists():
            tmp_dest.unlink(missing_ok=True)
        _copy_file_fsync(src_p, tmp_dest)
        _log(logger, verbose, "atomic_move.copied", ts=_now_iso(), tmp=str(tmp_dest), tmp_size=tmp_dest.stat().st_size)
        os.replace(str(tmp_dest), str(dest_p))
        _fsync_dir(dest_p.parent)
        _log(logger, verbose, "atomic_move.replaced", ts=_now_iso(), final=str(dest_p), final_size=dest_p.stat().st_size)
        # Remove source best-effort
        try:
            src_p.unlink(missing_ok=True)
            _log(logger, verbose, "atomic_move.source_removed", ts=_now_iso(), src=str(src_p))
        except Exception:
            pass

    if strict_verify and dest_p.exists():
        digest = _sha256(dest_p)
        _log(logger, verbose, "atomic_move.sha256", ts=_now_iso(), file=str(dest_p), sha256=digest)


def safety_copy_current_db(db_path: str, timestamp: str, *, verbose: bool = False, logger: Optional[logging.Logger] = None) -> str:
    """
    Create a safety copy folder adjacent to the DB file:
      <db_dir>/pre-restore-<timestamp>/
    Copy the DB file and its -wal/-shm companions if present.
    Return the safety folder path.

    Optional:
      - verbose/logger: emit copy steps and sizes.
    """
    db = Path(db_path).resolve()
    if not db.exists():
        raise RuntimeError(f"Database file not found for safety copy: {db}")
    out_dir = db.parent / f"pre-restore-{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Core DB file
    _copy_file_fsync(db, out_dir / db.name)
    _log(logger, verbose, "safety_copy.file", ts=_now_iso(), src=str(db), dst=str(out_dir / db.name), size=(out_dir / db.name).stat().st_size)

    # Companion files (WAL/SHM)
    for suffix in ("-wal", "-shm"):
        comp = Path(str(db) + suffix)
        if comp.exists() and comp.is_file():
            _copy_file_fsync(comp, out_dir / comp.name)
            _log(logger, verbose, "safety_copy.file", ts=_now_iso(), src=str(comp), dst=str(out_dir / comp.name), size=(out_dir / comp.name).stat().st_size)

    _fsync_dir(out_dir)
    _log(logger, verbose, "safety_copy.done", ts=_now_iso(), dir=str(out_dir.resolve()))
    return str(out_dir.resolve())


def replace_db_with(
    source_db_file: str,
    target_db_path: str,
    *,
    verbose: bool = False,
    logger: Optional[logging.Logger] = None,
    strict_verify: bool = False,
) -> None:
    """
    Replace the live DB file with `source_db_file` safely.

    Steps:
      - Ensure target directory exists.
      - Remove lingering target -wal/-shm files, if any.
      - Copy source to a temp file in the target directory and fsync.
      - os.replace() temp → target (atomic on same volume).
      - fsync target directory.

    Optional:
      - verbose/logger: emit swap steps, sizes and timestamps.
      - strict_verify: compute SHA-256 of the final target and log it.
    """
    src = Path(source_db_file).resolve()
    tgt = Path(target_db_path).resolve()
    if not src.exists() or not src.is_file():
        raise RuntimeError(f"Source DB file not found: {src}")

    tgt.parent.mkdir(parents=True, exist_ok=True)
    _log(logger, verbose, "replace_db.start", ts=_now_iso(), src=str(src), src_size=src.stat().st_size, target=str(tgt))

    # Remove any stale WAL/SHM for the target DB
    for suffix in ("", "-wal", "-shm"):
        stale = Path(str(tgt) + suffix) if suffix else tgt
        if stale.exists():
            try:
                size_before = stale.stat().st_size if stale.is_file() else 0
                stale.unlink()
                _log(logger, verbose, "replace_db.remove_stale", ts=_now_iso(), path=str(stale), size=size_before)
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
    _log(logger, verbose, "replace_db.copied", ts=_now_iso(), tmp=str(tmp), tmp_size=tmp.stat().st_size)

    # Atomic replace
    os.replace(str(tmp), str(tgt))
    _fsync_dir(tgt.parent)
    _log(logger, verbose, "replace_db.replaced", ts=_now_iso(), final=str(tgt), final_size=tgt.stat().st_size)

    if strict_verify and tgt.exists():
        digest = _sha256(tgt)
        _log(logger, verbose, "replace_db.sha256", ts=_now_iso(), file=str(tgt), sha256=digest)
