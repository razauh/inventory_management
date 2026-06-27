from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any


def to_json_text(value: Any) -> str:
    return json.dumps(_safe_json(value), sort_keys=True, separators=(",", ":"))


def from_json_text(value: str | None) -> Any:
    if not value:
        return {}
    return json.loads(value)


def _safe_json(value: Any) -> Any:
    if is_dataclass(value):
        return _safe_json(asdict(value))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
