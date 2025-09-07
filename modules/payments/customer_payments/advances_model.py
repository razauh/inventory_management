# inventory_management/modules/payments/customer_payments/advances_model.py
"""
customer_payments/advances_model.py

A read-only UI adapter over the existing History service and CustomerAdvances repo.
Loads the customer advances ledger & balance and offers tiny, pure helpers that UIs
can use for summaries and "how much credit can be applied" previews.

No DB writes. No business rules beyond simple min/max clamps that mirror repo guards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional


# ---------- Data shapes ----------

@dataclass(frozen=True)
class AdvanceRow:
    tx_id: int
    customer_id: int
    tx_date: str                   # 'YYYY-MM-DD'
    amount: float                  # +ve = deposit/credit, -ve = applied_to_sale
    source_type: str               # 'deposit' | 'applied_to_sale' | 'return_credit' | ...
    source_id: Optional[str]       # sale_id when source_type='applied_to_sale'
    notes: Optional[str]
    created_by: Optional[int]


@dataclass(frozen=True)
class LedgerPayload:
    entries: List[AdvanceRow]      # chronological (tx_date ASC, tx_id ASC)
    balance: float                 # from v_customer_advance_balance


# ---------- Model ----------

class CustomerAdvancesModel:
    """
    Thin, read-only adapter. Keep it decoupled from concrete classes by receiving factories.
      - history_service_factory(db_path) -> instance exposing:
          * advances_ledger(customer_id) -> {'entries': [...], 'balance': float}
          * (optional) overview(customer_id) or summary/customer overview via full_history
          * timeline(customer_id) -> list[dict]
          * (optional) full_history(customer_id) -> dict with 'summary', 'advances', 'timeline', ...
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

    # ---- Loads ----

    def load_ledger(self, customer_id: int) -> LedgerPayload:
        """
        Fetch ledger entries + current balance for the customer.
        """
        data = self._history_svc.advances_ledger(customer_id)
        entries_raw = list(data.get("entries", []))
        balance = float(data.get("balance", 0.0))

        entries: List[AdvanceRow] = []
        for r in entries_raw:
            entries.append(
                AdvanceRow(
                    tx_id=int(r.get("tx_id")),
                    customer_id=int(r.get("customer_id")),
                    tx_date=str(r.get("tx_date")),
                    amount=float(r.get("amount", 0.0)),
                    source_type=str(r.get("source_type")),
                    source_id=(None if r.get("source_id") in (None, "") else str(r.get("source_id"))),
                    notes=(None if r.get("notes") in (None, "") else str(r.get("notes"))),
                    created_by=(None if r.get("created_by") in (None, "") else int(r.get("created_by"))),
                )
            )
        # History service guarantees chronological order; don't re-sort here.
        return LedgerPayload(entries=entries, balance=balance)

    def load_overview_snapshot(self, customer_id: int) -> Dict[str, Any]:
        """
        Return a small overview dict:
          { 'credit_balance', 'sales_count', 'open_due_sum',
            'last_sale_date', 'last_payment_date', 'last_advance_date' }
        Prefer a direct 'overview'/'summary' call; otherwise derive from full_history.
        """
        svc = self._history_svc

        # Try several well-known access paths without assuming a single one exists.
        if hasattr(svc, "overview"):
            ov = svc.overview(customer_id)
            return dict(ov)

        if hasattr(svc, "summary"):
            sm = svc.summary(customer_id)
            return dict(sm)

        if hasattr(svc, "full_history"):
            fh = svc.full_history(customer_id)
            summary = dict(fh.get("summary", {}))
            return summary

        # Fallback: stitch balance and safe defaults (keeps UI alive even with a minimal service)
        bal = 0.0
        try:
            bal = float(self._adv_repo.get_balance(customer_id))
        except Exception:
            pass
        return {
            "credit_balance": bal,
            "sales_count": 0,
            "open_due_sum": 0.0,
            "last_sale_date": None,
            "last_payment_date": None,
            "last_advance_date": None,
        }

    def load_timeline(self, customer_id: int) -> List[Dict[str, Any]]:
        """
        Return merged chronological events for the customer:
          kinds: 'sale', 'receipt', 'advance', 'advance_applied'
        """
        return list(self._history_svc.timeline(customer_id))

    # ---- UI helpers (pure math, no writes) ----

    def max_applicable_credit(
        self,
        *,
        remaining_due: float,
        credit_balance: float,
    ) -> float:
        """
        Maximum credit that can be applied right now:
          = min(remaining_due >= 0, credit_balance >= 0)
        Mirrors repo guard.
        """
        rem = remaining_due if remaining_due and remaining_due > 0 else 0.0
        bal = credit_balance if credit_balance and credit_balance > 0 else 0.0
        return min(rem, bal)

    def summarize(self, ledger: LedgerPayload) -> Dict[str, Any]:
        """
        Return simple aggregates for UI footers / info panels.
        """
        entries = ledger.entries
        deposits = sum(a.amount for a in entries if a.amount > 0)
        applications = sum(-a.amount for a in entries if a.amount < 0)  # positive magnitude
        first_date = entries[0].tx_date if entries else None
        last_date = entries[-1].tx_date if entries else None
        return {
            "count": len(entries),
            "deposits": float(deposits),
            "applications": float(applications),
            "net_balance": float(ledger.balance),
            "first_tx_date": first_date,
            "last_tx_date": last_date,
        }
