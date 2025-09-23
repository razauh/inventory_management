# utils/validators.py

def non_empty(text: str) -> bool:
    """
    True if `text` is not None/empty after stripping whitespace.
    """
    return bool(text and str(text).strip())


# ---- Numeric parsing & validators ----

def try_parse_float(x):
    """
    Best-effort parse to float.

    Returns:
        (ok: bool, value: float|None)

    ok == False means parsing failed and value is None.
    """
    try:
        return True, float(x)
    except Exception:
        return False, None


def parse_float(x) -> float:
    """
    Strict parse to float; raises ValueError with a clear message on failure.
    Useful when callers want to *surface* parse errors rather than silently
    treating them as invalid.
    """
    ok, val = try_parse_float(x)
    if not ok:
        raise ValueError(f"Could not parse '{x}' as a number.")
    return val  # type: ignore[return-value]


def is_non_negative_number(x) -> bool:
    """
    True iff x parses to a float and value >= 0.
    """
    ok, val = try_parse_float(x)
    return bool(ok and val is not None and val >= 0)


def is_strictly_positive_number(x) -> bool:
    """
    True iff x parses to a float and value > 0.
    """
    ok, val = try_parse_float(x)
    return bool(ok and val is not None and val > 0)


# ---- Backward compatibility ----

def is_positive_number(x) -> bool:
    """
    Deprecated: prefer is_strictly_positive_number() or is_non_negative_number().

    Historically, this returned True for 0 as well (>= 0). To avoid breaking
    callers, we keep that behavior here. Update call sites to the clearer
    helpers above where appropriate.
    """
    return is_non_negative_number(x)
