"""
payment_utilities/calculations.py

Pure helpers for payment/credit UI previews. Mirrors the math used by:
- CustomerHistoryService.sales_with_items() for remaining_due (clamped >= 0).
- Purchase header roll-ups (cleared-only policy).

Do not import repos or open DB connections here.
Only compute numbers; formatting belongs in the UI.
"""
from __future__ import annotations

from typing import Tuple

__all__ = [
    "clamp_non_negative",
    "remaining_due_sale",
    "project_sale_after_receipt",
    "remaining_payable_purchase",
    "project_purchase_after_payment",
    "max_credit_applicable",
    "split_return_value",
    "status_from_paid",
]


# -----------------------------
# Core utilities
# -----------------------------

def clamp_non_negative(x: float) -> float:
    """Return x if x > 0, else 0.0.

    Mirrors history service clamping where receivable/payable never goes below zero.
    """
    return x if x > 0.0 else 0.0


# -----------------------------
# Sales helpers
# -----------------------------

def remaining_due_sale(
    calculated_total_amount: float,
    paid_amount: float,
    advance_payment_applied: float,
) -> float:
    """
    remaining_due = calculated_total_amount - paid_amount - advance_payment_applied,
    clamped at >= 0.

    Notes:
    - Use *calculated* total (from sale_detailed_totals), not the header total.
    - No rounding inside; UIs may format for display.
    """
    raw = calculated_total_amount - paid_amount - advance_payment_applied
    return clamp_non_negative(raw)


def project_sale_after_receipt(
    *,
    calculated_total_amount: float,
    current_paid_amount: float,
    current_advance_applied: float,  # kept for signature parity; status ignores this directly
    new_receipt_amount: float,
) -> Tuple[float, str]:
    """
    Returns (projected_paid_amount, projected_status).

    Status rules (same as triggers/UI copy):
      - 'paid'    if paid_amount >= calculated_total_amount
      - 'partial' if 0 < paid_amount <  calculated_total_amount
      - 'unpaid'  if paid_amount == 0

    Customer receipts affect header totals regardless of clearing state.
    """
    projected_paid = current_paid_amount + new_receipt_amount
    status = status_from_paid(calculated_total_amount, projected_paid)
    return projected_paid, status


# -----------------------------
# Purchase helpers (cleared-only policy)
# -----------------------------

def remaining_payable_purchase(
    total_amount: float,
    cleared_paid_amount: float,
    advance_payment_applied: float = 0.0,
) -> float:
    """
    remaining_payable = total_amount - cleared_paid_amount - advance_payment_applied,
    clamped at >= 0.

    Purchases roll up ONLY cleared payments into header 'paid_amount'.
    """
    raw = total_amount - cleared_paid_amount - advance_payment_applied
    return clamp_non_negative(raw)


def project_purchase_after_payment(
    *,
    total_amount: float,
    current_cleared_paid_amount: float,
    current_advance_applied: float,  # present for parity; status is based on cleared paid vs total
    new_payment_amount: float,
    new_payment_clearing_state: str,
) -> Tuple[float, str]:
    """
    Returns (projected_cleared_paid_amount, projected_status) under cleared-only policy.
    If new payment is 'cleared', it changes the header immediately; otherwise, it doesn't.

    Status rules (compare against total_amount):
      - 'paid'    if cleared_paid >= total_amount
      - 'partial' if 0 < cleared_paid < total_amount
      - 'unpaid'  if cleared_paid == 0
    """
    cleared = current_cleared_paid_amount
    if (new_payment_clearing_state or "").lower() == "cleared":
        cleared = cleared + new_payment_amount
    status = status_from_paid(total_amount, cleared)
    return cleared, status


# -----------------------------
# Credit helpers (customer/vendor symmetric)
# -----------------------------

def max_credit_applicable(remaining_due_or_payable: float, credit_balance: float) -> float:
    """
    The maximum advance/credit you can apply right now.
    = min(remaining_due_or_payable (clamped ≥0), credit_balance (clamped ≥0))
    """
    a = clamp_non_negative(remaining_due_or_payable)
    b = clamp_non_negative(credit_balance)
    return a if a < b else b


def split_return_value(
    returned_value: float,
    max_cash_refund_now: float,
) -> Tuple[float, float]:
    """
    Given the computed returned_value and a cap for immediate cash refund,
    return (cash_refund_now, credit_out).

    cash_refund_now is clamped to [0, min(returned_value, max_cash_refund_now)];
    credit_out = returned_value - cash_refund_now (≥ 0).
    """
    rv = clamp_non_negative(returned_value)
    cap = clamp_non_negative(max_cash_refund_now)
    cash_now_cap = rv if rv < cap else cap
    # In UIs, callers choose a cash refund up to this cap; here we return the maximal feasible split.
    cash_refund_now = cash_now_cap
    credit_out = rv - cash_refund_now
    return cash_refund_now, credit_out


# -----------------------------
# Common status helper
# -----------------------------

def status_from_paid(total: float, paid: float) -> str:
    """
    Threshold helper for status badges:
      - 'paid'    if paid >= total
      - 'partial' if 0 < paid < total
      - 'unpaid'  if paid == 0

    Notes:
    - No rounding is performed; use UI for formatting/epsilon if desired.
    - Negative totals are not expected; logic follows the defined thresholds.
    """
    if paid >= total:
        return "paid"
    if paid > 0:
        return "partial"
    return "unpaid"
