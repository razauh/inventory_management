# database/repositories/customer_advances_repo.py
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from decimal import Decimal

from modules.accounting import AccountingService, CustomerCreditApplicationPayload, CustomerCreditPayload


class CustomerAdvancesRepo:
    """
    Helpers for the customer_advances ledger.

    Conventions:
      • Deposits and return credits ADD credit (positive amounts).
      • Applications to a sale CONSUME credit (written as negative amounts).
      • DB trigger (e.g., trg_advances_no_overdraw) prevents overall overdraw.
      • v_customer_advance_balance view provides current balance by customer.

    source_type values:
      - 'deposit'
      - 'return_credit'
      - 'applied_to_sale'
    """

    def __init__(self, db_path: str | Path | sqlite3.Connection):
        if isinstance(db_path, sqlite3.Connection):
            self.conn = db_path
            self.db_path = None
        else:
            self.db_path = str(db_path)
            self.conn = None

    # ---- internals --------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self.conn is not None:
            class ConnectionWrapper:
                def __init__(self, conn):
                    self.conn = conn
                def __enter__(self):
                    return self.conn
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
            return ConnectionWrapper(self.conn)

        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON;")
        return con

    @staticmethod
    def _clamp_non_negative(x: float) -> float:
        return x if x > 0 else 0.0

    # ---- API --------------------------------------------------------------
    # NOTE: Method names aligned with controllers/actions expectations.
    #       Backward-compatible wrappers are provided at the bottom of the class.

    def grant_credit(
        self,
        *,
        customer_id: int,
        amount: float,
        date: Optional[str] = None,
        method: Optional[str] = None,
        bank_account_id: Optional[int] = None,
        reference_no: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        if method is None:
            method = "Other"
            reference_no = reference_no or "Legacy API credit"
        if method not in {"Cash", "Bank Transfer", "Card", "Cheque", "Other"}:
            raise ValueError("Select a valid customer credit method.")
        if method in {"Bank Transfer", "Card", "Cheque"} and bank_account_id is None:
            raise ValueError("A company bank account is required for this method.")
        if method != "Cash" and not (reference_no or "").strip():
            raise ValueError("A reference is required for non-cash customer credit.")

        with self._connect() as con:
            result = AccountingService(con).record_customer_credit_event(
                CustomerCreditPayload(
                    customer_id=customer_id, amount=Decimal(str(amount)),
                    source_type="deposit", date=date,
                    method=method, bank_account_id=bank_account_id,
                    reference_no=reference_no, notes=notes, created_by=created_by,
                )
            )
            return result.tx_id

    def add_return_credit(
        self,
        *,
        customer_id: int,
        amount: float,
        sale_id: Optional[str] = None,
        date: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        if amount is None or float(amount) <= 0:
            raise ValueError("Return credit amount must be a positive number.")
        with self._connect() as con:
            result = AccountingService(con).record_customer_credit_event(
                CustomerCreditPayload(
                    customer_id=customer_id, amount=Decimal(str(amount)),
                    source_type="return_credit", source_id=sale_id,
                    date=date, notes=notes, created_by=created_by,
                )
            )
            return result.tx_id

    def apply_credit_to_sale(
        self,
        *,
        customer_id: int,
        sale_id: str,
        amount: float,
        date: Optional[str] = None,
        created_by: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> int:
        if not sale_id:
            raise ValueError("sale_id is required to apply credit.")
        if amount is None or float(amount) <= 0:
            raise ValueError("Apply amount must be a positive number.")
        with self._connect() as con:
            result = AccountingService(con).record_customer_credit_application_event(
                CustomerCreditApplicationPayload(
                    customer_id=customer_id, sale_id=sale_id,
                    amount=Decimal(str(amount)),
                    date=date, notes=notes, created_by=created_by,
                )
            )
            return result.tx_id

    def get_balance(self, customer_id: int) -> float:
        with self._connect() as con:
            bal = AccountingService(con).get_customer_credit_balance(customer_id)
            return float(bal.balance)

    def list_ledger(self, customer_id: int) -> list[sqlite3.Row]:
        with self._connect() as con:
            rows = AccountingService(con).list_customer_credit_ledger(customer_id)
            return [dict(
                tx_id=r.tx_id, customer_id=r.customer_id, tx_date=r.tx_date,
                amount=float(r.amount), source_type=r.source_type,
                source_id=r.source_id, method=r.method,
                bank_account_id=r.bank_account_id, reference_no=r.reference_no,
                notes=r.notes, created_by=r.created_by,
            ) for r in rows]

    # ---- Backward-compatible wrappers (do not remove without updating callers) ----

    def add_deposit(
        self,
        *,
        customer_id: int,
        amount: float,
        date: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        return self.grant_credit(
            customer_id=customer_id, amount=amount, date=date,
            method="Other", reference_no="Legacy API credit",
            notes=notes, created_by=created_by,
        )

    def apply_to_sale(
        self,
        *,
        customer_id: int,
        sale_id: str,
        amount: float,
        date: Optional[str] = None,
        created_by: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> int:
        """Deprecated wrapper. Use apply_credit_to_sale()."""
        return self.apply_credit_to_sale(
            customer_id=customer_id,
            sale_id=sale_id,
            amount=amount,
            date=date,
            created_by=created_by,
            notes=notes,
        )


# Optional convenience factory
def get_customer_advances_repo(db_path: str | Path) -> CustomerAdvancesRepo:
    return CustomerAdvancesRepo(db_path)
