"""
modules/backup_restore/logging_utils.py

Purpose
-------
Uniform, append-only logging for Backup/Restore operations.

Public API
----------
- get_logger() -> logging.Logger
- log_event(logger, op, phase, message, extra: dict = {})
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

__all__ = ["get_logger", "log_event"]

# Default log file location (relative to app working directory)
_DEFAULT_LOG_DIR = Path("logs")
_DEFAULT_LOG_FILE = _DEFAULT_LOG_DIR / "backup_restore.log"

# Singleton cache so multiple calls don't add duplicate handlers
_LOGGER_NAME = "backup_restore"


def _ensure_log_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Best effort; if directory creation fails, fall back to stderr logging only.
        pass


def get_logger(file_path: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
    """
    Return a configured logger that writes JSON-lines to logs/backup_restore.log by default.
    Reuses the same logger (no duplicate handlers) across calls.

    Args:
        file_path: Optional custom path to the log file.
        level: Logging level (default INFO).
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False  # don't duplicate to root

    # If already configured with a handler, return as is
    if logger.handlers:
        return logger

    # File handler
    log_file = Path(file_path) if file_path else _DEFAULT_LOG_FILE
    _ensure_log_dir(log_file.parent)

    try:
        fh = logging.FileHandler(str(log_file), mode="a", encoding="utf-8", delay=True)
    except Exception:
        # If file handler can't be created, silently fall back to stderr only
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(_JsonLineFormatter())
        logger.addHandler(sh)
        return logger

    fh.setLevel(level)
    fh.setFormatter(_JsonLineFormatter())
    logger.addHandler(fh)

    # Also mirror to stderr at WARNING+ (useful when running tests/CI)
    sh = logging.StreamHandler()
    sh.setLevel(logging.WARNING)
    sh.setFormatter(_JsonLineFormatter())
    logger.addHandler(sh)

    return logger


class _JsonLineFormatter(logging.Formatter):
    """
    Minimal JSON-lines formatter:
      {"ts":"2025-09-16T12:00:01.123Z","level":"INFO","name":"backup_restore","msg":"...","extra":{...}}
    """
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload = {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        # Attach extra dict if provided via our helper
        if hasattr(record, "extra_payload") and isinstance(record.extra_payload, dict):
            payload["extra"] = record.extra_payload
        return json.dumps(payload, ensure_ascii=False)


def log_event(
    logger: logging.Logger,
    op: str,
    phase: str,
    message: str,
    extra: Dict[str, object] | None = None,
    level: int = logging.INFO,
) -> None:
    """
    Log a structured event line. Intended for backup/restore operational telemetry.

    Args:
        logger: Obtained from get_logger().
        op: Operation name, e.g., "backup" or "restore".
        phase: Phase within the operation, e.g., "preflight", "snapshot", "verify", "swap".
        message: Human-readable short message.
        extra: Optional additional key/values (file paths, sizes, durations, success flags).
        level: Logging level (default INFO).
    """
    extra_payload = {"op": op, "phase": phase}
    if extra:
        # Merge without overwriting the required keys
        for k, v in extra.items():
            if k not in extra_payload:
                extra_payload[k] = v

    # Attach our extra dict in a dedicated attribute the formatter will pick up
    logger.log(level, message, extra={"extra_payload": extra_payload})
