from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Iterable

_DANGEROUS_PREFIXES = ("=", "+", "-", "@")
_NUMERIC_TEXT_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?%?$")


def _looks_numeric_text(value: str) -> bool:
    text = value.strip()
    return bool(text) and bool(_NUMERIC_TEXT_RE.fullmatch(text))


def safe_csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return value

    text = str(value)
    stripped = text.lstrip(" \t\r\n")
    if stripped and stripped[0] in _DANGEROUS_PREFIXES and not _looks_numeric_text(stripped):
        return "'" + text
    return text


def safe_csv_row(values: Iterable[Any]) -> list[Any]:
    return [safe_csv_cell(value) for value in values]
