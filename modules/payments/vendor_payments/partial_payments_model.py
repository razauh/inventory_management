# inventory_management/modules/payments/vendor_payments/partial_payments_model.py
"""
UI-only helper for partial vendor payments on a single purchase.

- remaining_payable = total_amount - paid_amount_cleared (clamped ≥ 0)
- projects status preview based on CLEARED-only policy
- suggests common splits (pay remaining, half, N parts)
- no DB writes; persistence via PurchasePaymentsRepo.record_payment(...)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple


STATUS_UNPAID = "unpaid"
STATUS_PARTIAL = "partial"
STATUS_PAID = "paid"


@dataclass(frozen=True)
class PurchaseSnapshot:
    purchase_id: str
    total_amount: float                 # header total
    paid_amount_cleared: float          # sum of CLEARED payments (triggers’ basis)


@dataclass
class Suggestion:
    label: str
    amount: float
    note: Optional[str] = None


class VendorPartialPaymentsModel:
    """
    UI-only helper for partial vendor payments on a single purchase.

    It computes remaining payable (cleared-only policy), projects status for previews,
    and provides suggested split plans for a user-entered amount.
    """

    def __init__(self, *, currency_step: float = 0.01) -> None:
        self.step = float(currency_step)

    # ------------------------------------------------------------------ core math

    def remaining_payable(self, snap: PurchaseSnapshot) -> float:
        remaining = float(snap.total_amount) - float(snap.paid_amount_cleared)
        return max(0.0, remaining)

    def project_after_payment(self, snap: PurchaseSnapshot, pay_amount_now: float) -> Tuple[float, str]:
        paid_prime = float(snap.paid_amount_cleared) + float(max(0.0, pay_amount_now))
        total = float(snap.total_amount)
        if total > 0 and paid_prime >= total:
            return paid_prime, STATUS_PAID
        if paid_prime > 0:
            return paid_prime, STATUS_PARTIAL
        return paid_prime, STATUS_UNPAID

    def clamp_to_remaining(self, snap: PurchaseSnapshot, pay_amount_now: float) -> float:
        entered = max(0.0, float(pay_amount_now))
        return min(entered, self.remaining_payable(snap))

    # ---------------------------------------------------------------- suggestions

    def suggestions(self, snap: PurchaseSnapshot) -> List[Suggestion]:
        rem = self._round_to_step(self.remaining_payable(snap))
        if rem <= 0:
            return []
        out: List[Suggestion] = []
        # Pay remaining
        _, status = self.project_after_payment(snap, rem)
        note = "Will mark purchase as paid" if status == STATUS_PAID else None
        out.append(Suggestion("Pay remaining", rem, note))

        # Pay 50% of remaining
        half = self._round_to_step(rem / 2.0)
        _, status2 = self.project_after_payment(snap, half)
        note2 = None if status2 == STATUS_PAID else "Keeps status partial"
        out.append(Suggestion("Pay 50% of remaining", half, note2))

        # Optional thirds for quick picks
        third = self._round_to_step(rem / 3.0)
        two_thirds = self._round_to_step(rem - third)
        out.append(Suggestion("Pay ~⅓ of remaining", third, "Keeps status partial"))
        out.append(Suggestion("Pay ~⅔ of remaining", two_thirds, "Likely keeps status partial"))

        return out

    def split_even(self, total: float, n_parts: int) -> List[float]:
        if n_parts <= 0:
            return []
        total = max(0.0, float(total))
        base = self._round_down_to_step(total / n_parts)
        parts = [base] * n_parts
        used = base * n_parts
        residue = self._round_to_step(total - used)
        # distribute +step while residue remains
        i = 0
        while residue >= self.step - 1e-12 and i < n_parts:
            parts[i] = self._round_to_step(parts[i] + self.step)
            residue = self._round_to_step(residue - self.step)
            i += 1
        return parts

    def split_half_then_rest(self, total: float) -> List[float]:
        total = max(0.0, float(total))
        half = self._round_to_step(total / 2.0)
        rest = self._round_to_step(max(0.0, total - half))
        return [half, rest]

    # --------------------------------------------------------------- UI envelope

    def make_envelope(
        self,
        snap: PurchaseSnapshot,
        entered_amount: float,
        *,
        strategy: str = "cap_to_remaining",
    ) -> Dict:
        warnings: List[str] = []
        suggestions = self.suggestions(snap)

        remaining = self._round_to_step(self.remaining_payable(snap))
        entered = self._round_to_step(max(0.0, float(entered_amount)))

        if remaining == 0.0:
            return {
                "purchase_id": snap.purchase_id,
                "entered_amount": entered,
                "remaining_before": remaining,
                "allocated_now": 0.0,
                "remaining_after": remaining,
                "projected_status_after": STATUS_UNPAID,
                "plan": {"strategy": strategy, "parts": []},
                "warnings": ["This purchase has no remaining payable."],
                "suggestions": suggestions,
            }

        if entered == 0.0:
            warnings.append("Nothing to allocate.")

        # Decide allocation
        alloc: float
        plan_parts: List[float] = []
        if strategy == "half_now":
            half = self._round_to_step(remaining / 2.0)
            alloc = min(entered, half)
            plan_parts = self.split_half_then_rest(remaining)
        elif strategy.startswith("n_parts:"):
            try:
                n = int(strategy.split(":", 1)[1])
            except Exception:
                n = 2
            capped = min(entered, remaining)
            plan_parts = self.split_even(capped, max(1, n))
            alloc = self._round_to_step(sum(plan_parts))
        else:  # default: cap_to_remaining
            alloc = min(entered, remaining)

        alloc = self._round_to_step(alloc)
        if entered > remaining and remaining > 0:
            warnings.append("Capped to remaining payable.")

        _, status = self.project_after_payment(snap, alloc)

        return {
            "purchase_id": snap.purchase_id,
            "entered_amount": entered,
            "remaining_before": remaining,
            "allocated_now": alloc,
            "remaining_after": self._round_to_step(max(0.0, remaining - alloc)),
            "projected_status_after": status,
            "plan": {"strategy": strategy, "parts": plan_parts},
            "warnings": warnings,
            "suggestions": suggestions,
        }

    # --------------------------------------------------------------- rounding

    def _round_to_step(self, x: float) -> float:
        step = self.step
        if step <= 0:
            return float(x)
        q = int((x / step) + (0.5 if x >= 0 else -0.5))
        return q * step

    def _round_down_to_step(self, x: float) -> float:
        step = self.step
        if step <= 0:
            return float(x)
        return int(x / step) * step
