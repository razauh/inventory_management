from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from config import DATA_PATH


_LOGGER_NAME = "updater"
_DEFAULT_LOG_FILE = DATA_PATH / "logs" / "updater.log"


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload = {
            "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        extra_payload = getattr(record, "extra_payload", None)
        if isinstance(extra_payload, dict):
            payload["extra"] = extra_payload
        return json.dumps(payload, ensure_ascii=False)


def get_logger(file_path: str | None = None) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    log_file = Path(file_path) if file_path else _DEFAULT_LOG_FILE
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(str(log_file), mode="a", encoding="utf-8", delay=True)
    except Exception:
        handler = logging.StreamHandler()

    handler.setFormatter(_JsonLineFormatter())
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, phase: str, message: str, **extra: object) -> None:
    logger.info(message, extra={"extra_payload": {"phase": phase, **extra}})
