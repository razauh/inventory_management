# inventory_management/modules/payments/customer_payments/advance_applications_model.py
"""
customer_payments/advance_applications_model.py

Tiny UI adapter to help apply customer credit to a single sale.
- Boots with sale remaining_due (from History Service) and available credit (from Advances repo)
- Validates operator-entered amount against repo guards
- Emits a payload suitable for CustomerAdvancesRepo.apply_credit_to_sale(...)

No DB writes here; the controller calls the repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass(frozen=True)
class ApplyCreditContext:
    customer_id: int
    sale_id: str
    sale_remaining_due: float        # >= 0
    credit_balance: float            # >= 0
    date: Optional[str] = None       # 'YYYY-MM-DD'
    notes: Optional[str] = None
    created_by: Optional[int] = None


class AdvanceApplicationsModel:
    """
    Keep decoupled via factories:
      - history_service_factory(db_path) -> instance exposing:
            * full_history(customer_id) -> dict with 'sales'
            * (optional) sale_remaining_due(sale_id) or a targeted accessor
      - advances_repo_factory(db_path) -> instance exposing:
            * get_balance(customer_id) -> float
    """

    def __init__(
        self,
        history_service_factory: Callable[[str], Any],
        advances_repo_factory: Callable[[str], Any],
        db_path: str,
    ) -> None:
        self._history_svc = history_service_factory(db_path)
        self._adv_repo = advances_repo_factory(db_path)

    # ---- Bootstrapping ----

    def bootstrap(self, customer_id: int, sale_id: str) -> ApplyCreditContext:
        """
        Resolve remaining_due for the sale and available credit for the customer.
        Uses full_history(...) to locate the sale row and read 'remaining_due'.
        Falls back gracefully if data is missing (treat as 0).
        """
        remaining_due = 0.0

        # Prefer a targeted accessor if present
        if hasattr(self._history_svc, "sale_remaining_due"):
            try:
                remaining_due = float(self._history_svc.sale_remaining_due(sale_id))
            except Exception:
                remaining_due = 0.0
        else:
            # Fallback: scan full_history.sales
            try:
                fh = self._history_svc.full_history(customer_id)
                for s in fh.get("sales", []):
                    if str(s.get("sale_id")) == str(sale_id):
                        remaining_due = float(s.get("remaining_due", 0.0))
                        break
            except Exception:
                remaining_due = 0.0

        # Credit balance from repo (or fallback via history advances_ledger if needed)
        credit_balance = 0.0
        try:
            credit_balance = float(self._adv_repo.get_balance(customer_id))
        except Exception:
            try:
                adv = self._history_svc.advances_ledger(customer_id)
                credit_balance = float(adv.get("balance", 0.0))
            except Exception:
                credit_balance = 0.0

        return ApplyCreditContext(
            customer_id=customer_id,
            sale_id=str(sale_id),
            sale_remaining_due=max(0.0, remaining_due),
            credit_balance=max(0.0, credit_balance),
        )

    # ---- Helpers ----

    def max_applicable(self, ctx: ApplyCreditContext) -> float:
        """
        The hard cap imposed by repo rules:
          min(remaining_due, available credit), both clamped ≥ 0
        """
        return min(max(0.0, ctx.sale_remaining_due), max(0.0, ctx.credit_balance))

    def suggest_amount(self, ctx: ApplyCreditContext) -> float:
        """
        A friendly default for a one-click "Apply" action.
        """
        return self.max_applicable(ctx)

    def validate_amount(self, ctx: ApplyCreditContext, amount: float) -> None:
        """
        Raise ValueError with concise, user-facing text on invalid inputs,
        mirroring repo guards & controller copy.
        """
        try:
            amt = float(amount)
        except Exception:
            raise ValueError("Enter a valid positive amount to apply.")

        if amt <= 0:
            raise ValueError("Enter a valid positive amount to apply.")

        if ctx.sale_remaining_due <= 0:
            raise ValueError("This sale has no remaining due.")

        if ctx.credit_balance <= 0:
            raise ValueError("Customer has no available credit to apply.")

        if amt > ctx.sale_remaining_due:
            raise ValueError("Cannot apply credit beyond remaining due.")

        if amt > ctx.credit_balance:
            raise ValueError("Insufficient customer credit.")

    def to_repo_payload(self, ctx: ApplyCreditContext, amount: float) -> Dict[str, Any]:
        """
        Build the exact payload for CustomerAdvancesRepo.apply_credit_to_sale(...).
        NOTE: This sends the POSITIVE magnitude; the repo writes a NEGATIVE row
              with source_type='applied_to_sale' under the hood.
        """
        self.validate_amount(ctx, amount)
        return {
            "customer_id": ctx.customer_id,
            "sale_id": ctx.sale_id,
            "amount": float(amount),  # positive magnitude
            "date": ctx.date,
            "notes": ctx.notes,
            "created_by": ctx.created_by,
        }
