# database/repositories/customer_advances_repo.py
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


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

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)

    # ---- internals --------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
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
        date: Optional[str] = None,          # 'YYYY-MM-DD' (defaults to CURRENT_DATE)
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        """
        Grant customer credit via a direct deposit (positive amount).
        Returns the new tx_id.
        """
        if amount is None or float(amount) <= 0:
            raise ValueError("Deposit amount must be a positive number.")

        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO customer_advances
                    (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
                VALUES
                    (:customer_id, COALESCE(:tx_date, CURRENT_DATE), :amount, 'deposit', NULL, :notes, :created_by)
                """,
                {
                    "customer_id": customer_id,
                    "tx_date": date,
                    "amount": float(amount),
                    "notes": notes,
                    "created_by": created_by,
                },
            )
            return int(cur.lastrowid)

    def add_return_credit(
        self,
        *,
        customer_id: int,
        amount: float,
        sale_id: Optional[str] = None,       # SO id that originated the credit (optional tag)
        date: Optional[str] = None,
        notes: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> int:
        """
        Add customer credit resulting from a return (positive amount).
        Optionally tags the entry with the originating sale_id in source_id.
        Returns the new tx_id.
        """
        if amount is None or float(amount) <= 0:
            raise ValueError("Return credit amount must be a positive number.")

        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO customer_advances
                    (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
                VALUES
                    (:customer_id, COALESCE(:tx_date, CURRENT_DATE), :amount, 'return_credit', :source_id, :notes, :created_by)
                """,
                {
                    "customer_id": customer_id,
                    "tx_date": date,
                    "amount": float(amount),
                    "source_id": sale_id,
                    "notes": notes,
                    "created_by": created_by,
                },
            )
            return int(cur.lastrowid)

    def apply_credit_to_sale(
        self,
        *,
        customer_id: int,
        sale_id: str,
        amount: float,                        # positive here; will be written as negative
        date: Optional[str] = None,
        created_by: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Apply existing customer credit to a sale (consumes credit).
        Writes a NEGATIVE amount. Final over-application prevention is enforced by DB triggers.

        Soft checks (for clearer messages before the DB enforces):
          - amount must be positive.
          - sale must exist, be doc_type='sale', and belong to the customer.
          - will not apply more than the sale's remaining due:
              remaining_due = total_amount - paid_amount - advance_payment_applied
            (advance_payment_applied is expected to be maintained by DB triggers)
        Returns the new tx_id.
        """
        if not sale_id:
            raise ValueError("sale_id is required to apply credit.")
        if amount is None or float(amount) <= 0:
            raise ValueError("Apply amount must be a positive number.")

        with self._connect() as con:
            # Validate sale exists, is a real sale, and belongs to the customer
            row = con.execute(
                """
                SELECT sale_id,
                       customer_id,
                       COALESCE(total_amount, 0.0)            AS total_amount,
                       COALESCE(paid_amount, 0.0)              AS paid_amount,
                       COALESCE(advance_payment_applied, 0.0)  AS advance_payment_applied,
                       doc_type
                  FROM sales
                 WHERE sale_id = ?;
                """,
                (sale_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"Sale '{sale_id}' does not exist.")
            if row["doc_type"] != "sale":
                raise ValueError("Cannot apply credit to a quotation; only real sales are allowed.")
            if int(row["customer_id"]) != int(customer_id):
                raise ValueError("Sale does not belong to the specified customer.")

            total_amount = float(row["total_amount"] or 0.0)
            paid_amount = float(row["paid_amount"] or 0.0)
            adv_applied = float(row["advance_payment_applied"] or 0.0)

            remaining_due = self._clamp_non_negative(total_amount - paid_amount - adv_applied)

            if float(amount) > (remaining_due + 1e-9):
                raise ValueError(
                    f"Cannot apply {float(amount):.2f}; remaining due on sale is {remaining_due:.2f}."
                )

            # Insert application (negative amount). DB trigger ensures overall balance suffices.
            cur = con.execute(
                """
                INSERT INTO customer_advances
                    (customer_id, tx_date, amount, source_type, source_id, notes, created_by)
                VALUES
                    (:customer_id, COALESCE(:tx_date, CURRENT_DATE), :neg_amount,
                     'applied_to_sale', :source_id, :notes, :created_by)
                """,
                {
                    "customer_id": customer_id,
                    "tx_date": date,
                    "neg_amount": -abs(float(amount)),
                    "source_id": sale_id,
                    "notes": notes,
                    "created_by": created_by,
                },
            )
            return int(cur.lastrowid)

    def get_balance(self, customer_id: int) -> float:
        """
        Fetch the current credit balance for a customer from v_customer_advance_balance.
        Returns 0.0 when no rows exist.
        """
        with self._connect() as con:
            row = con.execute(
                "SELECT balance FROM v_customer_advance_balance WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
            return float(row["balance"]) if row and row["balance"] is not None else 0.0

    # (Optional) helpful for UIs / history
    def list_ledger(self, customer_id: int) -> list[sqlite3.Row]:
        with self._connect() as con:
            cur = con.execute(
                """
                SELECT *
                  FROM customer_advances
                 WHERE customer_id = ?
                 ORDER BY tx_date ASC, tx_id ASC;
                """,
                (customer_id,),
            )
            return cur.fetchall()

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
        """Deprecated wrapper. Use grant_credit()."""
        return self.grant_credit(
            customer_id=customer_id,
            amount=amount,
            date=date,
            notes=notes,
            created_by=created_by,
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
