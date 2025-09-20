"""
modules/backup_restore/validators.py

Purpose
-------
Centralize common preflight checks with clear, user-friendly error messages.

Public API
---------
- validate_backup_destination(dest_file: str, db_size: int, free_space: int) -> None
- validate_backup_source(db_path: str) -> None
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


def _human_size(num: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(0, int(num)))
    for u in units:
        if size < 1024.0 or u == units[-1]:
            return f"{size:.1f} {u}"
        size /= 1024.0


def _is_writable_dir(p: Path) -> bool:
    try:
        return p.exists() and p.is_dir() and os.access(str(p), os.W_OK | os.X_OK)
    except Exception:
        return False


def _windows_reserved_names() -> Iterable[str]:
    return {
        "con", "prn", "aux", "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }


def validate_backup_destination(dest_file: str, db_size: int, free_space: int) -> None:
    """
    Validate that the destination path can receive a backup file.

    Rules:
      - Parent folder must exist and be writable.
      - Filename must be non-empty and not a directory.
      - Recommend .imsdb extension (not strictly required here).
      - Require at least 1.5x DB size in free space (caller passes free_space).
    Raises:
      RuntimeError with a user-facing message on failure.
    """
    if db_size < 0:
        raise RuntimeError("Database size is invalid (negative bytes reported).")

    path = Path(dest_file)
    parent = path.parent if path.parent != Path("") else Path.cwd()

    # Parent folder
    if not parent.exists():
        raise RuntimeError(f"Destination folder does not exist: {parent}")
    if not _is_writable_dir(parent):
        raise RuntimeError(f"Destination folder is not writable: {parent}")

    # Name checks
    name = path.name.strip()
    if not name:
        raise RuntimeError("Please provide a file name for the backup.")
    if sys.platform.startswith("win"):
        stem = path.stem.lower().rstrip(".")
        if stem in _windows_reserved_names():
            raise RuntimeError(f"The backup filename '{path.stem}' is reserved on Windows.")
        # Disallow trailing spaces/dots in Windows filenames
        if path.name.endswith((" ", ".")):
            raise RuntimeError("Windows filenames cannot end with a space or dot.")

    if path.exists() and path.is_dir():
        raise RuntimeError("Destination path points to a directory, not a file.")

    # Space check: require ~1.5x DB size buffer
    required = int(max(0, db_size) * 1.5)
    if free_space < required:
        raise RuntimeError(
            "Not enough free space in the destination folder.\n"
            f"Required (approx): {_human_size(required)}\n"
            f"Available: {_human_size(free_space)}"
        )

    # Gentle nudge on extension (non-fatal)
    if path.suffix.lower() != ".imsdb":
        # Not an error, just guidance for the caller (service enforces final extension)
        # Raise a soft warning by exception? No—validators should not be chatty.
        # Leave as pass; controller/service may append the extension.
        pass


def validate_backup_source(db_path: str) -> None:
    """
    Validate that the source DB exists and is readable before attempting snapshot.

    Rules:
      - DB path must exist and be a regular file.
      - Read permission must be available.
      - Size must be > 0 bytes (heuristic sanity).
    Raises:
      RuntimeError with a user-facing message on failure.
    """
    p = Path(db_path)
    if not p.exists():
        raise RuntimeError(f"Database file not found: {p}")
    if not p.is_file():
        raise RuntimeError(f"Database path is not a file: {p}")
    if not os.access(str(p), os.R_OK):
        raise RuntimeError(f"Database file is not readable: {p}")
    try:
        size = p.stat().st_size
    except Exception:
        size = 0
    if size <= 0:
        raise RuntimeError(
            "The database file appears to be empty or unreadable (0 bytes). "
            "Please verify the active database location."
        )
