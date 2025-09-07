"""
payment_utilities/partial_payment_manager.py

UI-only helpers to split a single entered amount across multiple documents.

- For customers: allocate across open sales (field: remaining_due).
- For vendors:   allocate across open purchases (field: remaining_payable).

Pure functions; no DB. Does not enforce banking/clearing rules.
Persistence remains 1 payment row per document via the appropriate repository.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, InvalidOperation, getcontext

# Keep plenty of precision for intermediate math; round only with helpers below
getcontext().prec = 28

# -----------------------------
# Strategy enum (strings)
# -----------------------------
STRATEGY_OLDEST_FIRST = "oldest_first"
STRATEGY_DUE_DATE = "due_date"
STRATEGY_BIGGEST_FIRST = "biggest_remaining"
STRATEGY_PROPORTIONAL = "proportional"

__all__ = [
    "STRATEGY_OLDEST_FIRST",
    "STRATEGY_DUE_DATE",
    "STRATEGY_BIGGEST_FIRST",
    "STRATEGY_PROPORTIONAL",
    "allocate_customer_payment",
    "allocate_vendor_payment",
    "round_down_to_step",
    "round_to_step",
    "clamp",
    "sum_remaining_sales",
    "sum_remaining_purchases",
]

# -----------------------------
# Rounding & utility helpers
# -----------------------------

def _to_decimal(x: Any) -> Decimal:
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _step_quant(step: float) -> Decimal:
    d = _to_decimal(step)
    # Ensure step like 0.01 produces quant 0.01; fallback to 0.01 if invalid/zero
    if d <= 0:
        d = Decimal("0.01")
    # Normalize to exponent (e.g., 0.01 -> '0.01')
    return d


def round_down_to_step(x: float, step: float) -> float:
    """Round DOWN (floor) to the nearest step using Decimal for determinism."""
    q = _step_quant(step)
    dec = _to_decimal(x)
    # Convert to multiples of step, floor, then back
    # Example: x=10.037, step=0.01 -> 10.03
    if q == 0:
        return float(dec)
    multiples = (dec / q).to_integral_value(rounding=ROUND_DOWN)
    return float(multiples * q)


def round_to_step(x: float, step: float) -> float:
    """Round to nearest step using **half-up** (typical financial rounding)."""
    q = _step_quant(step)
    dec = _to_decimal(x)
    if q == 0:
        return float(dec)
    # Quantize to step granularity with HALF_UP
    # Example: x=10.005, step=0.01 -> 10.01
    return float((dec / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * q)


def clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _safe_remaining(val: Any) -> float:
    try:
        f = float(val)
        return f if f > 0 else 0.0
    except Exception:
        return 0.0


def sum_remaining_sales(sales: List[Dict[str, Any]]) -> float:
    return float(sum(_safe_remaining(s.get("remaining_due", 0.0)) for s in sales))


def sum_remaining_purchases(purchases: List[Dict[str, Any]]) -> float:
    return float(sum(_safe_remaining(p.get("remaining_payable", 0.0)) for p in purchases))


# -----------------------------
# Core allocation engine (generic)
# -----------------------------

def _allocate(
    amount: float,
    docs: List[Dict[str, Any]],
    *,
    id_key: str,
    remaining_key: str,
    kind_label: str,  # 'sale' | 'purchase'
    strategy: str,
    currency_step: float,
    user_overrides: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    requested_total = max(0.0, float(amount or 0.0))

    # Build working list, filter zero-remaining
    work: List[Dict[str, Any]] = []
    for d in docs:
        rem = _safe_remaining(d.get(remaining_key, 0.0))
        if rem <= 0:
            continue
        work.append({
            id_key: d.get(id_key),
            "date": d.get("date"),
            # allow optional due_date if caller supplied; else None
            "due_date": d.get("due_date"),
            "remaining": rem,
            "alloc": 0.0,
            "locked": False,
        })

    warnings: List[str] = []
    if requested_total == 0.0:
        warnings.append("Nothing to allocate.")
    if not work:
        return {
            "requested_total": requested_total,
            "allocated_total": 0.0,
            "unallocated": requested_total,
            "rows": [],
            "warnings": warnings or ["No open balance to allocate."],
        }

    pool = requested_total

    # Apply user overrides
    overrides = user_overrides or {}
    by_id = {w[id_key]: w for w in work}
    for oid, ovalue in overrides.items():
        row = by_id.get(oid)
        if row is None:
            continue
        v = max(0.0, float(ovalue or 0.0))
        headroom = max(0.0, row["remaining"] - row["alloc"])
        v = min(v, headroom, pool)
        v = round_down_to_step(v, currency_step)
        if v <= 0.0:
            continue
        row["alloc"] += v
        row["locked"] = True
        pool -= v
        if pool <= 0.0:
            pool = 0.0
            break

    # Sort according to strategy
    def _key_oldest(w: Dict[str, Any]):
        return (w.get("date") or "", str(w.get(id_key)))

    def _key_due(w: Dict[str, Any]):
        # Use due_date if present; fallback to date
        return (w.get("due_date") or w.get("date") or "", str(w.get(id_key)))

    def _key_biggest(w: Dict[str, Any]):
        return (-float(w.get("remaining", 0.0)), w.get("date") or "", str(w.get(id_key)))

    if strategy == STRATEGY_BIGGEST_FIRST:
        work.sort(key=_key_biggest)
    elif strategy == STRATEGY_DUE_DATE:
        work.sort(key=_key_due)
    else:  # default oldest_first (also used for proportional residue ordering)
        work.sort(key=_key_oldest)

    # Auto-fill
    if strategy == STRATEGY_PROPORTIONAL and pool > 0.0:
        # Compute weights only across UNLOCKED rows with headroom
        unlocked = [w for w in work if not w["locked"] and (w["remaining"] - w["alloc"]) > 0]
        total_remaining = sum((w["remaining"] - w["alloc"]) for w in unlocked)
        if total_remaining > 0:
            for w in unlocked:
                weight = (w["remaining"] - w["alloc"]) / total_remaining
                want = pool * weight
                want = min(want, w["remaining"] - w["alloc"])  # cap to headroom
                want = round_down_to_step(want, currency_step)
                if want > 0:
                    w["alloc"] += want
            # recompute pool based on allocations
            allocated_now = sum(w["alloc"] for w in work) - sum(
                round_down_to_step(overrides.get(w[id_key], 0.0), currency_step) for w in work if w["locked"]
            )
            pool = max(0.0, requested_total - allocated_now)
    else:
        for w in work:
            if pool <= 0.0:
                break
            if w["locked"]:
                continue
            headroom = w["remaining"] - w["alloc"]
            if headroom <= 0:
                continue
            want = min(headroom, pool)
            want = round_down_to_step(want, currency_step)
            if want <= 0:
                continue
            w["alloc"] += want
            pool -= want

    # Residual top-up distribution (give +step to rows with headroom by sort order)
    step = float(_step_quant(currency_step))
    # Round the pool to step; if >= step, keep topping up
    # Use a safety counter to avoid infinite loops
    safety = 0
    while pool >= step - 1e-12 and safety < 10000:
        topped = False
        for w in work:
            if pool < step:
                break
            headroom = w["remaining"] - w["alloc"]
            if headroom >= step - 1e-12:
                w["alloc"] += step
                pool -= step
                topped = True
        if not topped:
            break
        safety += 1

    # Build output rows and totals
    out_rows: List[Dict[str, Any]] = []
    for w in work:
        alloc_amt = round_to_step(w["alloc"], currency_step)
        if alloc_amt <= 0.0:
            continue
        if kind_label == "sale":
            out_rows.append({
                "document_kind": "sale",
                "sale_id": w[id_key],
                "amount": alloc_amt,
            })
        else:
            out_rows.append({
                "document_kind": "purchase",
                "purchase_id": w[id_key],
                "amount": alloc_amt,
            })

    allocated_total = round_to_step(sum(r["amount"] for r in out_rows), currency_step)
    unallocated = round_to_step(requested_total - allocated_total, currency_step)

    # Warnings
    combined_remaining = sum(w["remaining"] for w in work)
    if requested_total > combined_remaining and unallocated > 0:
        warnings.append("Requested amount exceeds combined remaining; some amount left unallocated.")
    if allocated_total == 0.0 and requested_total > 0.0:
        if "Nothing to allocate." not in warnings:
            warnings.append("Nothing to allocate.")

    return {
        "requested_total": requested_total,
        "allocated_total": allocated_total,
        "unallocated": unallocated,
        "rows": out_rows,
        "warnings": warnings,
    }


# -----------------------------
# Public allocation functions
# -----------------------------

def allocate_customer_payment(
    amount: float,
    sales: List[Dict[str, Any]],
    *,
    strategy: str = STRATEGY_OLDEST_FIRST,
    currency_step: float = 0.01,
    user_overrides: Optional[Dict[str, float]] = None,  # sale_id -> amount
) -> Dict[str, Any]:
    """Split 'amount' across given sales. Returns an allocation plan envelope."""
    return _allocate(
        amount,
        sales,
        id_key="sale_id",
        remaining_key="remaining_due",
        kind_label="sale",
        strategy=strategy,
        currency_step=currency_step,
        user_overrides=user_overrides,
    )


def allocate_vendor_payment(
    amount: float,
    purchases: List[Dict[str, Any]],
    *,
    strategy: str = STRATEGY_OLDEST_FIRST,
    currency_step: float = 0.01,
    user_overrides: Optional[Dict[str, float]] = None,  # purchase_id -> amount
) -> Dict[str, Any]:
    """Split 'amount' across given purchases. Returns an allocation plan envelope."""
    return _allocate(
        amount,
        purchases,
        id_key="purchase_id",
        remaining_key="remaining_payable",
        kind_label="purchase",
        strategy=strategy,
        currency_step=currency_step,
        user_overrides=user_overrides,
    )
