# inventory_management/modules/payments/vendor_payments/advances_model.py
"""
Read-only UI adapter for vendor advances (credit):
- Loads ledger entries and current balance from VendorAdvancesRepo.
- Provides 'as-of' credit and open payables snapshot matching Reporting/Aging.
- Pure reads; no DB writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class AdvanceRow:
    tx_id: int
    vendor_id: int
    tx_date: str                   # 'YYYY-MM-DD'
    amount: float                  # +ve deposit/return_credit; -ve applied_to_purchase
    source_type: str               # 'deposit' | 'return_credit' | 'applied_to_purchase' | ...
    source_id: Optional[str]       # purchase_id when applied; else None
    notes: Optional[str]
    created_by: Optional[int]


@dataclass(frozen=True)
class LedgerPayload:
    entries: List[AdvanceRow]      # chronological by DATE(tx_date), then tx_id
    balance: float                 # running sum (current balance)


class VendorAdvancesModel:
    """
    Read-only UI adapter for vendor credit (advances).
    Wraps VendorAdvancesRepo (ledger/balance) and ReportingRepo (as-of snapshots).
    """

    def __init__(
        self,
        advances_repo_factory: Callable[[str], Any],
        reporting_repo_factory: Callable[[str], Any],
        db_path: str,
    ) -> None:
        self._db_path = db_path
        self._adv = advances_repo_factory(db_path)
        self._rep = reporting_repo_factory(db_path)

    # ---- Loads ----
    def load_ledger(
        self,
        vendor_id: int,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> LedgerPayload:
        """
        Fetch chronological ledger rows (+ current balance) for a vendor.
        """
        raw_rows = self._adv.list_ledger(vendor_id, date_from, date_to)
        entries: List[AdvanceRow] = []
        for r in raw_rows or []:
            entries.append(
                AdvanceRow(
                    tx_id=int(r.get("tx_id")),
                    vendor_id=int(r.get("vendor_id")),
                    tx_date=str(r.get("tx_date")),
                    amount=float(r.get("amount", 0.0) or 0.0),
                    source_type=str(r.get("source_type", "")),
                    source_id=(None if r.get("source_id") in (None, "") else str(r.get("source_id"))),
                    notes=(None if r.get("notes") in (None, "") else str(r.get("notes"))),
                    created_by=(None if r.get("created_by") in (None, "") else int(r.get("created_by"))),
                )
            )
        balance = float(self._adv.get_balance(vendor_id))
        return LedgerPayload(entries=entries, balance=balance)

    def load_as_of(self, vendor_id: int, as_of: str) -> Dict[str, float]:
        """
        Return {"credit_balance": float, "open_payables_sum": float} as of a cutoff date.
        - credit_balance: SUM(vendor_advances.amount) up to 'as_of'
        - open_payables_sum: sum over purchases of max(0, total - paid - advance_applied)
                             where 'paid' on purchases reflects CLEARED-only policy.
        """
        credit = float(self._rep.vendor_credit_as_of(vendor_id, as_of))
        headers = self._rep.vendor_headers_as_of(vendor_id, as_of)
        open_sum = 0.0
        for h in headers or []:
            total = float(h.get("total_amount", 0.0) or 0.0)
            paid = float(h.get("paid_amount", 0.0) or 0.0)
            adv = float(h.get("advance_payment_applied", 0.0) or 0.0)
            rem = total - paid - adv
            if rem > 0:
                open_sum += rem
        return {"credit_balance": credit, "open_payables_sum": open_sum}

    # ---- Convenience summaries (pure) ----
    def summarize(self, payload: LedgerPayload) -> Dict[str, object]:
        """
        Return a small summary for UI headers/footers.
        """
        deposits = sum(e.amount for e in payload.entries if e.amount > 0)
        applications = sum(-e.amount for e in payload.entries if e.amount < 0)  # positive magnitude
        first_tx = payload.entries[0].tx_date if payload.entries else None
        last_tx = payload.entries[-1].tx_date if payload.entries else None
        return {
            "count": len(payload.entries),
            "deposits": deposits,
            "applications": applications,
            "net_balance": payload.balance,
            "first_tx_date": first_tx,
            "last_tx_date": last_tx,
        }
