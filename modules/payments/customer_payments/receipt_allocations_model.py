"""
customer_payments/receipt_allocations_model.py

UI-only helper to split one customer receipt across multiple sales.
- Input: list of sales with 'remaining_due' and a common header (method, dates, bank fields...)
- Output: persistable rows (one per sale) for SalePaymentsRepo.record_payment(...)

No DB connections. No business rules beyond capping to remaining and rounding to currency step.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Iterable, Tuple

# ---- Strategies ----
STRATEGY_OLDEST_FIRST = "oldest_first"
STRATEGY_BIGGEST_FIRST = "biggest_remaining"
STRATEGY_PROPORTIONAL = "proportional"


@dataclass
class ReceiptAllocationHeader:
    method: str
    date: Optional[str] = None
    bank_account_id: Optional[int] = None
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
class SaleCandidate:
    sale_id: str
    date: str
    remaining_due: float


def round_down_to_step(x: float, step: float) -> float:
    """Floor to step; deterministic. Example: step=0.01 => floor cents."""
    try:
        x = float(x)
    except Exception:
        x = 0.0
    if step <= 0:
        return x
    q = int(x / step)
    return q * step


def round_to_step(x: float, step: float) -> float:
    """Half-up rounding to the given step (typical currency behavior)."""
    try:
        x = float(x)
    except Exception:
        x = 0.0
    if step <= 0:
        return x
    q = int((x / step) + (0.5 if x >= 0 else -0.5))
    return q * step


class ReceiptAllocationsModel:
    def __init__(self, header: ReceiptAllocationHeader, currency_step: float = 0.01) -> None:
        self._header: ReceiptAllocationHeader = header
        self._rows: List[SaleCandidate] = []
        self._step = float(currency_step or 0.01)

    def set_header(self, header: ReceiptAllocationHeader) -> None:
        self._header = header

    def candidates(self) -> List[SaleCandidate]:
        return list(self._rows)

    def set_candidates(self, rows: Iterable[dict]) -> None:
        """Replace internal candidates. Drop rows with non-positive remaining_due."""
        out: List[SaleCandidate] = []
        for r in rows or []:
            try:
                rd = float(r.get("remaining_due", 0.0))
            except Exception:
                rd = 0.0
            if rd <= 0:
                continue
            sale_id = str(r.get("sale_id"))
            date = str(r.get("date", ""))
            if not sale_id:
                continue
            out.append(SaleCandidate(sale_id=sale_id, date=date, remaining_due=rd))
        self._rows = out

    # ---- soft validation (minimal, UI-friendly) ----
    def _soft_validate_header(self) -> None:
        if not isinstance(self._header.method, str) or not self._header.method.strip():
            raise ValueError("Payment method is required for allocation header.")
        m = self._header.method
        bankish = {"Bank Transfer", "Cheque", "Cash Deposit"}
        if m == "Cash":
            if self._header.bank_account_id is not None:
                raise ValueError("Cash must not reference a company bank account.")
        elif m in bankish:
            if self._header.bank_account_id is None:
                raise ValueError(f"{m} requires a company bank account.")
            if not (self._header.instrument_no or "").strip():
                raise ValueError(f"{m} requires an instrument/reference number.")
        # Card/Other have no bank requirement here; repo will enforce other details if needed.

    # ---- allocation core ----
    def allocate(
        self,
        total_amount: float,
        *,
        strategy: str = STRATEGY_OLDEST_FIRST,
        user_overrides: Optional[Dict[str, float]] = None,
    ) -> dict:
        # normalize pool
        try:
            pool = float(total_amount or 0.0)
        except Exception:
            pool = 0.0
        if pool < 0:
            raise ValueError("Enter a positive amount to allocate.")

        # quick exits
        if not self._rows:
            return {
                "requested_total": pool,
                "allocated_total": 0.0,
                "unallocated": round_to_step(pool, self._step),
                "rows": [],
                "warnings": ["No open balance to allocate."] if pool > 0 else ["Nothing to allocate."]
            }
        if pool == 0:
            return {
                "requested_total": 0.0,
                "allocated_total": 0.0,
                "unallocated": 0.0,
                "rows": [],
                "warnings": ["Nothing to allocate."]
            }

        # header sanity checks
        self._soft_validate_header()

        # working maps
        alloc: Dict[str, float] = {}
        locked: Dict[str, bool] = {}

        # apply overrides
        remaining_by_id = {c.sale_id: c.remaining_due for c in self._rows}
        if user_overrides:
            for sid, val in user_overrides.items():
                if sid not in remaining_by_id:
                    continue
                try:
                    v = float(val or 0.0)
                except Exception:
                    v = 0.0
                v = max(0.0, v)
                v = min(v, remaining_by_id[sid])
                v = round_down_to_step(v, self._step)
                if v > 0:
                    alloc[sid] = v
                    locked[sid] = True
                    pool -= v
        # pool might go negative by rounding; clamp
        if pool < 0:
            pool = 0.0

        # choose order for auto-fill
        unlocked: List[SaleCandidate] = [c for c in self._rows if not locked.get(c.sale_id)]
        if strategy == STRATEGY_BIGGEST_FIRST:
            unlocked.sort(key=lambda c: (-float(c.remaining_due), c.date, c.sale_id))
        else:
            # oldest_first and default; proportional uses this order for residue distribution
            unlocked.sort(key=lambda c: (c.date, c.sale_id))

        # auto allocation
        if strategy == STRATEGY_PROPORTIONAL and unlocked:
            sum_rem = sum(float(c.remaining_due) for c in unlocked)
            targets: Dict[str, float] = {}
            if sum_rem > 0:
                for c in unlocked:
                    w = float(c.remaining_due) / sum_rem
                    targets[c.sale_id] = pool * w
            else:
                # fallback to equal split
                equal = pool / len(unlocked)
                for c in unlocked:
                    targets[c.sale_id] = equal
            # allocate rounded down to step
            for c in unlocked:
                headroom = float(c.remaining_due) - alloc.get(c.sale_id, 0.0)
                want = min(headroom, targets.get(c.sale_id, 0.0))
                want = round_down_to_step(want, self._step)
                if want > 0 and pool > 0:
                    want = min(want, pool)
                    alloc[c.sale_id] = alloc.get(c.sale_id, 0.0) + want
                    pool -= want
        else:
            for c in unlocked:
                if pool <= 0:
                    break
                headroom = float(c.remaining_due) - alloc.get(c.sale_id, 0.0)
                want = min(headroom, pool)
                want = round_down_to_step(want, self._step)
                if want > 0:
                    alloc[c.sale_id] = alloc.get(c.sale_id, 0.0) + want
                    pool -= want

        # distribute residue in step bumps while pool >= step and headroom exists
        if pool >= self._step:
            order = unlocked  # deterministic order
            for c in order:
                if pool < self._step:
                    break
                headroom = float(c.remaining_due) - alloc.get(c.sale_id, 0.0)
                if headroom >= self._step:
                    alloc[c.sale_id] = alloc.get(c.sale_id, 0.0) + self._step
                    pool -= self._step
            # one more pass if any remains
            if pool >= self._step:
                for c in order:
                    if pool < self._step:
                        break
                    headroom = float(c.remaining_due) - alloc.get(c.sale_id, 0.0)
                    if headroom >= self._step:
                        alloc[c.sale_id] = alloc.get(c.sale_id, 0.0) + self._step
                        pool -= self._step

        # build rows
        header_map = asdict(self._header)
        rows: List[Dict[str, object]] = []
        for sid, amt in alloc.items():
            amt = round_to_step(amt, self._step)
            if amt <= 0:
                continue
            r = {"sale_id": sid, "amount": amt}
            # copy header fields verbatim
            r.update(header_map)
            rows.append(r)

        allocated_total = sum(r["amount"] for r in rows) if rows else 0.0
        unallocated = round_to_step(float(total_amount) - allocated_total, self._step)

        warnings: List[str] = []
        combined_remaining = sum(c.remaining_due for c in self._rows)
        if float(total_amount) > combined_remaining and unallocated > 0:
            warnings.append("Requested amount exceeds combined remaining; some amount left unallocated.")
        if not rows:
            warnings.append("Nothing to allocate.")

        return {
            "requested_total": round_to_step(float(total_amount), self._step),
            "allocated_total": round_to_step(allocated_total, self._step),
            "unallocated": unallocated,
            "rows": rows,
            "warnings": warnings,
        }
