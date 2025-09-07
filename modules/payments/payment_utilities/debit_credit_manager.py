"""
payment_utilities/debit_credit_manager.py

UI-only helpers to classify cashflow direction and compute In/Out/Net totals
for lists of ledger-like rows, mirroring app semantics:

- sale_payments: receipts (>0) = inflow, refunds (<0) = outflow
- purchase_payments: pays (>0) = outflow, refunds (<0) = inflow
- advances (customer/vendor): non-bank by default (separate ledgers)

No DB connections. No business rules (e.g., header roll-ups or clearing effects).
Use 'where' and 'group_totals' to pivot by bank_account_id / instrument_type / clearing_state.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

__all__ = [
    "classify_direction",
    "is_bank_row",
    "split_in_out",
    "totals",
    "group_totals",
    "present_row",
]

# ----------- internals -----------

_KINDS_BANK = {"sale_payment", "purchase_payment"}


def _get(row: Dict[str, Any], key: str, default: Any = None) -> Any:
    return row.get(key, default)


# ----------- API -----------

def classify_direction(row: Dict[str, Any]) -> Tuple[str, float]:
    """
    Return ("inflow"|"outflow"|"none", magnitude: float>=0).
    - sale_payment: amount>0 => inflow; amount<0 => outflow
    - purchase_payment: amount>0 => outflow; amount<0 => inflow
    - advances (default): 'none' (not bank); keep magnitude=abs(amount) for non-bank summaries
    Unknown/zero => ('none', 0.0)
    """
    kind = str(_get(row, "kind", "")).strip().lower()
    try:
        amount = float(_get(row, "amount", 0.0) or 0.0)
    except Exception:
        amount = 0.0

    if amount == 0.0:
        return "none", 0.0

    if kind == "sale_payment":
        return ("inflow", abs(amount)) if amount > 0 else ("outflow", abs(amount))
    if kind == "purchase_payment":
        return ("outflow", abs(amount)) if amount > 0 else ("inflow", abs(amount))

    # customer_advance / vendor_advance / others → non-bank by default
    return "none", abs(amount)


def is_bank_row(row: Dict[str, Any]) -> bool:
    """
    True if row has a non-null bank_account_id and kind in {sale_payment, purchase_payment}.
    Advances are non-bank by default.
    """
    kind = str(_get(row, "kind", "")).strip().lower()
    if kind not in _KINDS_BANK:
        return False
    return _get(row, "bank_account_id", None) is not None


def split_in_out(rows: List[Dict[str, Any]], *, bank_only: bool = True) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Return (inflows, outflows).
    If bank_only=True, ignore rows where is_bank_row() is False.
    """
    inflows: List[Dict[str, Any]] = []
    outflows: List[Dict[str, Any]] = []
    for r in rows:
        if bank_only and not is_bank_row(r):
            continue
        direction, _mag = classify_direction(r)
        if direction == "inflow":
            inflows.append(r)
        elif direction == "outflow":
            outflows.append(r)
        else:
            # ignore 'none' for in/out split
            pass
    return inflows, outflows


def totals(
    rows: List[Dict[str, Any]],
    *,
    bank_only: bool = True,
    where: Dict[str, Any] | None = None,
) -> Dict[str, float]:
    """
    Return {"in": float, "out": float, "net": float}.
    Applies 'where' as an equality filter on row keys if provided.
    """
    total_in = 0.0
    total_out = 0.0

    def _match(r: Dict[str, Any]) -> bool:
        if where is None:
            return True
        for k, v in where.items():
            if _get(r, k, None) != v:
                return False
        return True

    for r in rows:
        if bank_only and not is_bank_row(r):
            continue
        if not _match(r):
            continue
        direction, mag = classify_direction(r)
        if direction == "inflow":
            total_in += mag
        elif direction == "outflow":
            total_out += mag
        # 'none' ignored

    return {"in": total_in, "out": total_out, "net": total_in - total_out}


def group_totals(
    rows: List[Dict[str, Any]],
    group_key: str,
    *,
    bank_only: bool = True,
    where: Dict[str, Any] | None = None,
) -> List[Tuple[object, Dict[str, float]]]:
    """
    Return sorted list of (group_value, {"in":..., "out":..., "net":...}).
    Sort groups by group_value natural order; callers can re-sort for UI.
    """
    buckets: Dict[object, Dict[str, float]] = {}

    def _match(r: Dict[str, Any]) -> bool:
        if where is None:
            return True
        for k, v in where.items():
            if _get(r, k, None) != v:
                return False
        return True

    for r in rows:
        if bank_only and not is_bank_row(r):
            continue
        if not _match(r):
            continue
        key = _get(r, group_key, None)
        direction, mag = classify_direction(r)
        if direction == "none":
            continue
        bucket = buckets.setdefault(key, {"in": 0.0, "out": 0.0, "net": 0.0})
        if direction == "inflow":
            bucket["in"] += mag
        elif direction == "outflow":
            bucket["out"] += mag
        bucket["net"] = bucket["in"] - bucket["out"]

    # Sort by natural order of key (Python tuple ordering handles None last if mixed types are avoided)
    return sorted(buckets.items(), key=lambda kv: (kv[0] is None, kv[0]))


def present_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a shallow copy with added keys:
      'direction': 'inflow'|'outflow'|'none',
      'abs_amount': abs(amount),
      'sign': 1|-1|0  (company perspective: +1=inflow, -1=outflow, 0=none)
    Leaves original keys untouched.
    """
    out = dict(row)
    direction, mag = classify_direction(row)
    sign = 0
    if direction == "inflow":
        sign = 1
    elif direction == "outflow":
        sign = -1
    out.update({
        "direction": direction,
        "abs_amount": mag,
        "sign": sign,
    })
    return out
