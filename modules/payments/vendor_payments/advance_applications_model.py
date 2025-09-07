# inventory_management/modules/payments/vendor_payments/advance_applications_model.py
"""
Thin UI helper to apply vendor credit to a single purchase:
- Bootstraps remaining payable (header: total - paid - advance_applied) and credit balance.
- Suggests/validates amount (cap = min(remaining, balance)).
- Emits payload for VendorAdvancesRepo.apply_credit_to_purchase(...); repo writes the NEGATIVE ledger row.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class ApplyVendorCreditContext:
    vendor_id: int
    purchase_id: str
    remaining_payable: float          # header remaining (>= 0)
    credit_balance: float             # vendor’s available credit (>= 0)
    date: Optional[str] = None        # 'YYYY-MM-DD' for ledger row
    notes: Optional[str] = None
    created_by: Optional[int] = None


class VendorAdvanceApplicationsModel:
    """
    UI helper to apply vendor credit to a purchase.
    Read-only until `to_repo_payload`; writes are done by VendorAdvancesRepo.
    """

    def __init__(
        self,
        advances_repo_factory: Callable[[str], Any],
        reporting_repo_factory: Callable[[str], Any],
        purchases_repo_factory: Callable[[str], Any],   # kept for flexibility if caller prefers
        db_path: str,
    ) -> None:
        self._db_path = db_path
        self._adv = advances_repo_factory(db_path)
        self._rep = reporting_repo_factory(db_path)
        self._purchases = purchases_repo_factory(db_path)

    # -------------------------------------------------------------- bootstrap

    def bootstrap(self, vendor_id: int, purchase_id: str) -> ApplyVendorCreditContext:
        """
        Read current remaining payable for the purchase and vendor credit balance.
        Remaining payable basis mirrors reporting/triggers:
            remaining = max(0, total_amount - paid_amount - advance_payment_applied)
        where paid_amount is CLEARED-only on purchases.
        """
        # Prefer using reporting repo 'as of today' for consistency across screens
        today = _dt.date.today().isoformat()
        headers = self._rep.vendor_headers_as_of(vendor_id, today) or []
        remaining = None
        for h in headers:
            if str(h.get("purchase_id")) == str(purchase_id):
                total = float(h.get("total_amount", 0.0) or 0.0)
                paid = float(h.get("paid_amount", 0.0) or 0.0)
                adv = float(h.get("advance_payment_applied", 0.0) or 0.0)
                remaining = max(0.0, total - paid - adv)
                break
        if remaining is None:
            # Fallback: try a direct header fetch if reporting path didn't include the purchase
            try:
                hdr = self._purchases.get_header(purchase_id)  # type: ignore[attr-defined]
                total = float(hdr.get("total_amount", 0.0) or 0.0)
                paid = float(hdr.get("paid_amount", 0.0) or 0.0)
                adv = float(hdr.get("advance_payment_applied", 0.0) or 0.0)
                remaining = max(0.0, total - paid - adv)
            except Exception:
                remaining = 0.0  # be defensive; repo call will still validate on apply

        credit = float(self._adv.get_balance(vendor_id))
        return ApplyVendorCreditContext(
            vendor_id=vendor_id,
            purchase_id=str(purchase_id),
            remaining_payable=remaining,
            credit_balance=max(0.0, credit),
        )

    # -------------------------------------------------------------- math helpers

    def max_applicable(self, ctx: ApplyVendorCreditContext) -> float:
        return min(max(0.0, float(ctx.remaining_payable)), max(0.0, float(ctx.credit_balance)))

    def suggest_amount(self, ctx: ApplyVendorCreditContext) -> float:
        return self.max_applicable(ctx)

    def validate_amount(self, ctx: ApplyVendorCreditContext, amount: float) -> None:
        amt = float(amount)
        if amt <= 0:
            raise ValueError("Amount must be positive.")
        if ctx.remaining_payable <= 0:
            raise ValueError("This purchase has no remaining payable.")
        if ctx.credit_balance <= 0:
            raise ValueError("Vendor has no available credit to apply.")
        if amt > ctx.remaining_payable:
            raise ValueError("Cannot apply credit beyond remaining payable.")
        if amt > ctx.credit_balance:
            raise ValueError("Insufficient vendor credit.")

    # -------------------------------------------------------------- payload

    def to_repo_payload(self, ctx: ApplyVendorCreditContext, amount: float) -> Dict[str, Any]:
        """
        Build kwargs for VendorAdvancesRepo.apply_credit_to_purchase(...).
        The repository will insert a NEGATIVE ledger row with source_type='applied_to_purchase'.
        """
        self.validate_amount(ctx, amount)
        return {
            "vendor_id": ctx.vendor_id,
            "purchase_id": ctx.purchase_id,
            "amount": float(amount),   # positive magnitude; repo will store negative
            "date": ctx.date,
            "notes": ctx.notes,
            "created_by": ctx.created_by,
        }
