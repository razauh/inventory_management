# inventory_management/modules/payments/vendor_payments/allocations_model.py
"""
UI-only allocator to split one vendor payout across multiple purchases.

- Inputs: purchases with remaining_payable (total - paid_cleared)
- Strategies: oldest_first / biggest_remaining / proportional + user overrides
- Output rows match PurchasePaymentsRepo.record_payment(**kwargs) exactly
- No business rules; DB/Triggers validate methods, banks, instruments
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Iterable, Dict, List


STRATEGY_OLDEST_FIRST = "oldest_first"
STRATEGY_BIGGEST_FIRST = "biggest_remaining"
STRATEGY_PROPORTIONAL = "proportional"


@dataclass
class AllocationHeader:
    method: str
    date: Optional[str] = None
    bank_account_id: Optional[int] = None
    vendor_bank_account_id: Optional[int] = None
    instrument_type: Optional[str] = None
    instrument_no: Optional[str] = None
    instrument_date: Optional[str] = None
    deposited_date: Optional[str] = None
    cleared_date: Optional[str] = None
    clearing_state: Optional[str] = None
    ref_no: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None


@dataclass
class PurchaseCandidate:
    purchase_id: str
    date: str
    remaining_payable: float  # >= 0, computed as total - paid_cleared


class VendorAllocationsModel:
    def __init__(self, header: AllocationHeader, currency_step: float = 0.01) -> None:
        self._header = header
        self._step = float(currency_step)
        self._candidates: List[PurchaseCandidate] = []

    def set_header(self, header: AllocationHeader) -> None:
        self._header = header

    def set_candidates(self, rows: Iterable[dict]) -> None:
        self._candidates = []
        for r in rows or []:
            rem = float(r.get("remaining_payable", 0.0) or 0.0)
            if rem <= 0:
                continue
            self._candidates.append(
                PurchaseCandidate(
                    purchase_id=str(r.get("purchase_id", "")),
                    date=str(r.get("date", "")),
                    remaining_payable=rem,
                )
            )

    def candidates(self) -> List[PurchaseCandidate]:
        return list(self._candidates)

    # ---------------------------------------------------------------- allocation

    def allocate(
        self,
        total_amount: float,
        *,
        strategy: str = STRATEGY_OLDEST_FIRST,
        user_overrides: Optional[Dict[str, float]] = None,
    ) -> Dict:
        warnings: List[str] = []
        pool = self._round_to_step(max(0.0, float(total_amount)))
        if pool == 0.0:
            warnings.append("Nothing to allocate.")
        if not self._candidates:
            return {
                "requested_total": pool,
                "allocated_total": 0.0,
                "unallocated": pool,
                "rows": [],
                "warnings": ["No open balance to allocate."] + warnings,
            }

        # Working state per candidate
        alloc: Dict[str, float] = {}
        locked: Dict[str, bool] = {}

        # 1) Apply overrides
        if user_overrides:
            idx = {c.purchase_id: c for c in self._candidates}
            for pid, val in user_overrides.items():
                c = idx.get(str(pid))
                if not c:
                    continue
                v = max(0.0, float(val))
                v = min(v, c.remaining_payable)
                v = self._round_down_to_step(min(v, pool))
                if v <= 0:
                    continue
                alloc[c.purchase_id] = v
                locked[c.purchase_id] = True
                pool = self._round_to_step(pool - v)
                if pool <= 0:
                    pool = 0.0
                    break

        # 2) Strategy order for unlocked
        unlocked = [c for c in self._candidates if not locked.get(c.purchase_id)]
        if strategy == STRATEGY_BIGGEST_FIRST:
            unlocked.sort(key=lambda c: (-c.remaining_payable, c.date, c.purchase_id))
        else:
            # oldest_first and default order
            unlocked.sort(key=lambda c: (c.date, c.purchase_id))

        # 3) Auto-fill
        if strategy == STRATEGY_PROPORTIONAL and unlocked:
            sum_rem = sum(c.remaining_payable for c in unlocked)
            if sum_rem > 0:
                # targets by proportion (floor to step)
                for c in unlocked:
                    if pool <= 0:
                        break
                    headroom = c.remaining_payable - alloc.get(c.purchase_id, 0.0)
                    if headroom <= 0:
                        continue
                    target = (pool * (c.remaining_payable / sum_rem)) if sum_rem else 0.0
                    want = self._round_down_to_step(min(headroom, target, pool))
                    if want <= 0:
                        continue
                    alloc[c.purchase_id] = alloc.get(c.purchase_id, 0.0) + want
                    pool = self._round_to_step(pool - want)
        else:
            for c in unlocked:
                if pool <= 0:
                    break
                headroom = c.remaining_payable - alloc.get(c.purchase_id, 0.0)
                if headroom <= 0:
                    continue
                want = self._round_down_to_step(min(headroom, pool))
                if want <= 0:
                    continue
                alloc[c.purchase_id] = alloc.get(c.purchase_id, 0.0) + want
                pool = self._round_to_step(pool - want)

        # 4) Distribute residue (+step bumps)
        order_for_residue = unlocked  # same as sort order for determinism
        i = 0
        while pool >= self._step - 1e-12 and i < len(order_for_residue):
            c = order_for_residue[i]
            headroom = c.remaining_payable - alloc.get(c.purchase_id, 0.0)
            if headroom >= self._step - 1e-12:
                bump = min(self._step, pool, headroom)
                bump = self._round_to_step(bump)
                if bump > 0:
                    alloc[c.purchase_id] = alloc.get(c.purchase_id, 0.0) + bump
                    pool = self._round_to_step(pool - bump)
            i += 1

        # 5) Build rows
        rows: List[Dict] = []
        for c in self._candidates:
            amt = self._round_to_step(alloc.get(c.purchase_id, 0.0))
            if amt <= 0:
                continue
            rows.append({
                "purchase_id": c.purchase_id,
                "amount": amt,  # positive: payout to vendor
                "method": self._header.method,
                "date": self._header.date,
                "bank_account_id": self._header.bank_account_id,
                "vendor_bank_account_id": self._header.vendor_bank_account_id,
                "instrument_type": self._header.instrument_type,
                "instrument_no": self._header.instrument_no,
                "instrument_date": self._header.instrument_date,
                "deposited_date": self._header.deposited_date,
                "cleared_date": self._header.cleared_date,
                "clearing_state": self._header.clearing_state,
                "ref_no": self._header.ref_no,
                "notes": self._header.notes,
                "created_by": self._header.created_by,
            })

        allocated_total = self._round_to_step(sum(r["amount"] for r in rows))
        unallocated = self._round_to_step(max(0.0, float(total_amount) - allocated_total))

        # Combined remaining across candidates (for warning)
        total_remaining = sum(c.remaining_payable for c in self._candidates)
        if allocated_total < float(total_amount) and float(total_amount) > total_remaining + 1e-12:
            warnings.append("Some amount left unallocated.")

        # Soft sanity (UI-only)
        if self._header.method == "Bank Transfer" and allocated_total > 0:
            if self._header.bank_account_id is None or self._header.vendor_bank_account_id is None:
                warnings.append("Bank Transfer requires both company and vendor bank accounts for outgoing payments.")

        if self._header.method == "Cash" and self._header.bank_account_id is not None:
            warnings.append("Cash payouts should not reference a company bank account.")

        if not rows:
            # If nothing could be allocated (e.g., pool too small vs step)
            if allocated_total == 0 and float(total_amount) > 0:
                warnings.append("Unable to allocate with the given currency step.")

        return {
            "requested_total": self._round_to_step(float(total_amount)),
            "allocated_total": allocated_total,
            "unallocated": unallocated,
            "rows": rows,
            "warnings": warnings,
        }

    # ---------------------------------------------------------------- rounding

    def _round_to_step(self, x: float) -> float:
        step = self._step
        if step <= 0:
            return float(x)
        q = int((x / step) + (0.5 if x >= 0 else -0.5))
        return q * step

    def _round_down_to_step(self, x: float) -> float:
        step = self._step
        if step <= 0:
            return float(x)
        return int(x / step) * step
