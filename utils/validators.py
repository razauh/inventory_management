def non_empty(text: str) -> bool:
    return bool(text and text.strip())

def is_positive_number(x) -> bool:
    try:
        return float(x) >= 0
    except Exception:
        return False
