# utils/helpers.py
from datetime import date
import logging
from typing import Union, Optional

NumberLike = Union[float, int, str]

_log = logging.getLogger(__name__)


def today_str() -> str:
    """Return today's date as ISO string (YYYY-MM-DD)."""
    return date.today().isoformat()


def fmt_money(
    v: NumberLike,
    places: int = 2,
    *,
    strict: bool = False,
    sentinel: Optional[str] = None,
) -> str:
    """
    Format a number as money with thousands separators and a fixed number of decimals.

    Behavior on parse failure:
      - By default (strict=False, sentinel=None), preserves legacy behavior and returns str(v).
      - If `sentinel` is provided (e.g., "N/A"), returns that sentinel instead.
      - If `strict=True`, raises ValueError on parse failures.

    Args:
        v: Value to format; will be parsed with float(v).
        places: Number of decimal places (default: 2).
        strict: If True, raise on parse errors; else fall back.
        sentinel: If not None and parsing fails, return this string.

    Returns:
        Formatted string, or fallback per the rules above.
    """
    try:
        x = float(v)
    except Exception as e:
        # Log at debug level to aid troubleshooting without spamming user logs.
        _log.debug("fmt_money: failed to parse %r as float: %s", v, e)
        if strict:
            raise ValueError(f"Could not parse {v!r} as a number.") from e
        return str(sentinel) if sentinel is not None else str(v)
    return f"{x:,.{places}f}"
