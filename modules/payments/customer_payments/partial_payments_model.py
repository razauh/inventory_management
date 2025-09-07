"""
inventory_management/modules/payments/customer_payments/partial_payments_model.py

UI-only helper for partial payments on a single sale.

- Mirrors remaining_due = calculated_total_amount - paid_amount - advance_payment_applied (clamped ≥ 0)
- Provides suggested amounts (pay remaining, half, N equal parts)
- Projects status after applying a proposed amount (unpaid/partial/paid) for preview only
- Does not touch DB; persistence still goes through SalePaymentsRepo.record_payment(...)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple


# ---- Status thresholds (sales) ----
STATUS_UNPAID: str = "unpaid"
STATUS_PARTIAL: str = "partial"
STATUS_PAID: str = "paid"


@dataclass(frozen=True)
class SaleSnapshot:
    sale_id: str
    calculated_total_amount: float
    paid_amount: float
    advance_payment_applied: float


@dataclass
class Suggestion:
    """A single suggestion line the UI can render as a quick action."""
    label: str                 # e.g., "Pay remaining", "50% now"
    amount: float              # suggested amount (rounded to step)
    note: Optional[str] = None # e.g., "Will mark the sale as paid"


class PartialPaymentsModel:
    """
    UI-only helper for partial payments on a single sale.

    It computes remaining due, projects status for previews,
    and provides suggested split plans for a user-entered amount.
    """

    def __init__(self, *, currency_step: float = 0.01) -> None:
        self.step = float(currency_step) if currency_step is not None else 0.01

    # ----------------- internal rounding helpers -----------------
    def _round_to_step(self, x: float) -> float:
        """
        Deterministic half-up rounding to the configured currency step.
        """
        step = self.step
        if step <= 0:
            return float(x)
        q = int((x / step) + (0.5 if x >= 0 else -0.5))
        return q * step

    def _round_down_to_step(self, x: float) -> float:
        """
        Floor to the nearest multiple of the currency step (towards -inf).
        Intended for even splits before distributing residue.
        """
        step = self.step
        if step <= 0:
            return float(x)
        return int(x / step) * step

    # ----------------- Core math (pure) -----------------
    def remaining_due(self, snap: SaleSnapshot) -> float:
        """
        remaining = calculated_total_amount - paid_amount - advance_payment_applied, clamped at >= 0
        """
        try:
            calc = float(snap.calculated_total_amount)
            paid = float(snap.paid_amount)
            adv = float(snap.advance_payment_applied)
        except Exception:
            # Be defensive; treat unparseable numbers as 0.0
            calc, paid, adv = 0.0, 0.0, 0.0
        remaining = calc - paid - adv
        return self._round_to_step(remaining if remaining > 0 else 0.0)

    def project_after_payment(self, snap: SaleSnapshot, pay_amount: float) -> Tuple[float, str]:
        """
        Returns (projected_paid_amount, projected_status).
        Sales headers consider sum of payments (clearing tracked but not gating).
        """
        calc_total = float(snap.calculated_total_amount)
        paid_prime = float(snap.paid_amount) + float(pay_amount)
        # Status thresholds
        if paid_prime >= calc_total:
            status = STATUS_PAID
        elif paid_prime == 0:
            status = STATUS_UNPAID
        else:
            status = STATUS_PARTIAL
        return paid_prime, status

    def clamp_to_remaining(self, snap: SaleSnapshot, pay_amount: float) -> float:
        """
        Cap the entered amount to remaining due (non-negative).
        """
        entered = max(0.0, float(pay_amount))
        remaining = self.remaining_due(snap)
        return self._round_to_step(min(entered, remaining))

    # ----------------- Suggestions for common UX patterns -----------------
    def suggestions(self, snap: SaleSnapshot) -> List[Suggestion]:
        """
        Build a small list of quick-action suggestions based on remaining due.
        """
        rem = self.remaining_due(snap)
        out: List[Suggestion] = []
        if rem <= 0:
            return out

        # 1) Pay remaining
        proj_paid, proj_status = self.project_after_payment(snap, rem)
        note = None
        if proj_status == STATUS_PAID:
            note = "Will mark the sale as paid"
        out.append(Suggestion(label="Pay remaining", amount=self._round_to_step(rem), note=note))

        # 2) Pay 50% of remaining
        half = self._round_to_step(rem / 2.0)
        if half > 0:
            _, st = self.project_after_payment(snap, half)
            note2 = "Will keep status partial" if st != STATUS_PAID else "Will mark the sale as paid"
            out.append(Suggestion(label="Pay 50% of remaining", amount=half, note=note2))

        # 3) Optional: 1/3 of remaining
        one_third = self._round_to_step(rem / 3.0)
        if one_third > 0 and all(abs(one_third - s.amount) > 1e-9 for s in out):
            _, st3 = self.project_after_payment(snap, one_third)
            note3 = "Will keep status partial" if st3 != STATUS_PAID else "Will mark the sale as paid"
            out.append(Suggestion(label="Pay ~33% of remaining", amount=one_third, note=note3))

        return out

    def split_even(self, total: float, n_parts: int) -> List[float]:
        """
        Split 'total' into n equal parts using round-down-to-step, then distribute residue (+step)
        to the earliest parts deterministically.
        """
        n = max(1, int(n_parts or 1))
        total = max(0.0, float(total))
        if n == 1:
            return [self._round_to_step(total)]

        base = self._round_down_to_step(total / n)
        parts = [base for _ in range(n)]
        allocated = base * n
        residue = total - allocated

        # distribute residue in increments of step while possible
        step = self.step if self.step > 0 else 0.01
        i = 0
        while residue + 1e-12 >= step:  # small epsilon to avoid float glitches
            parts[i] = self._round_to_step(parts[i] + step)
            residue -= step
            i = (i + 1) % n
        # Final tidy rounding for display
        parts = [self._round_to_step(x) for x in parts]
        # Adjust last part to ensure exact sum after rounding (best-effort)
        diff = self._round_to_step(total) - self._round_to_step(sum(parts))
        if abs(diff) >= step / 2:
            parts[-1] = self._round_to_step(parts[-1] + diff)
        return parts

    def split_half_then_rest(self, total: float) -> List[float]:
        """
        Return [half_rounded, total - half_rounded] with step rounding and non-negative clamp.
        """
        tot = max(0.0, float(total))
        half = self._round_to_step(tot / 2.0)
        rest = self._round_to_step(max(0.0, tot - half))
        # correct any tiny rounding mismatch
        diff = self._round_to_step(tot) - self._round_to_step(half + rest)
        if abs(diff) >= (self.step if self.step > 0 else 0.01) / 2:
            rest = self._round_to_step(rest + diff)
        return [half, rest]

    # ----------------- Build a controller-friendly envelope (no DB writes) -----------------
    def make_envelope(
        self,
        snap: SaleSnapshot,
        entered_amount: float,
        *,
        strategy: str = "cap_to_remaining",     # "cap_to_remaining" | "half_now" | "n_parts:<n>"
    ) -> Dict:
        """
        Return a dict envelope containing preview numbers, plan details, and suggestions.
        """
        warnings: List[str] = []

        # Normalize input
        try:
            entered = float(entered_amount)
        except Exception:
            entered = 0.0
        if entered < 0:
            # Negative (refund) is deliberately out-of-scope here
            warnings.append("Nothing to allocate.")
            entered = 0.0

        entered_r = self._round_to_step(entered)
        remaining = self.remaining_due(snap)

        if remaining == 0:
            return {
                "sale_id": snap.sale_id,
                "entered_amount": entered_r,
                "remaining_before": remaining,
                "allocated_now": 0.0,
                "remaining_after": remaining,
                "projected_status_after": STATUS_UNPAID if snap.paid_amount == 0 else STATUS_PARTIAL,
                "plan": {"strategy": strategy, "parts": []},
                "warnings": ["Sale has no remaining due."],
                "suggestions": [s.__dict__ for s in self.suggestions(snap)],
            }

        if entered == 0:
            warnings.append("Nothing to allocate.")

        # Apply strategy
        alloc = 0.0
        plan_parts: List[float] = []
        strat = strategy or "cap_to_remaining"

        if strat == "cap_to_remaining":
            alloc = self._round_to_step(min(entered, remaining))

        elif strat == "half_now":
            half = self._round_to_step(remaining / 2.0)
            # Allocate up to both half and entered
            alloc = self._round_to_step(min(half, entered, remaining))
            plan_parts = self.split_half_then_rest(min(entered, remaining))

        elif strat.startswith("n_parts:"):
            # parse n
            try:
                n_str = strat.split(":", 1)[1]
                n_val = int(n_str)
            except Exception:
                n_val = 2
            base_total = min(entered, remaining)
            plan_parts = self.split_even(base_total, max(1, n_val))
            # Today's allocation is the first part (UI may choose to take all today; spec keeps it as a presentation)
            alloc = self._round_to_step(plan_parts[0] if plan_parts else 0.0)

        else:
            # Unknown strategy → default to cap_to_remaining
            alloc = self._round_to_step(min(entered, remaining))

        if entered > remaining:
            warnings.append("Entered amount exceeds remaining; capped to remaining due.")

        remaining_after = self._round_to_step(max(0.0, remaining - alloc))
        _, proj_status = self.project_after_payment(snap, alloc)

        envelope: Dict = {
            "sale_id": snap.sale_id,
            "entered_amount": entered_r,
            "remaining_before": remaining,
            "allocated_now": self._round_to_step(alloc),
            "remaining_after": remaining_after,
            "projected_status_after": proj_status,
            "plan": {
                "strategy": strat,
                "parts": [self._round_to_step(p) for p in plan_parts] if plan_parts else [],
            },
            "warnings": warnings,
            "suggestions": [s.__dict__ for s in self.suggestions(snap)],
        }
        return envelope
