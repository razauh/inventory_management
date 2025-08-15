from datetime import date

def today_str() -> str:
    return date.today().isoformat()

def fmt_money(v: float | int | str, places: int = 2) -> str:
    try:
        x = float(v)
    except Exception:
        return str(v)
    return f"{x:,.{places}f}"