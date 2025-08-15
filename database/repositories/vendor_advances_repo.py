from __future__ import annotations
import sqlite3
from typing import Optional


class VendorAdvancesRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---------- Apply existing credit to a purchase (−amount) ----------
    def apply_credit_to_purchase(
        self,
        vendor_id: int,
        purchase_id: str,
        amount: float,
        *,
        date: str,
        notes: Optional[str],
        created_by: Optional[int],
    ) -> int:
        """
        Apply existing vendor credit to a specific purchase.

        Semantics:
          - Positive `amount` means "apply this much credit".
          - Stored as NEGATIVE in vendor_advances (credit consumed).
          - source_type='applied_to_purchase', source_id=purchase_id
          - Trigger prevents overdrawing credit and rolls up purchases.advance_payment_applied.
        """
        if amount <= 0:
            raise ValueError("amount must be positive when applying credit")

        applied = -abs(float(amount))  # store as negative (credit consumed)

        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO vendor_advances (
                    vendor_id, tx_date, amount, source_type, source_id, notes, created_by
                )
                VALUES (?, ?, ?, 'applied_to_purchase', ?, ?, ?)
                """,
                (vendor_id, date, applied, purchase_id, notes, created_by),
            )
            return int(cur.lastrowid)

    # ---------- Grant new credit (+amount), e.g., credit note for returns ----------
    def grant_credit(
        self,
        vendor_id: int,
        amount: float,
        *,
        date: str,
        notes: Optional[str],
        created_by: Optional[int],
        # optional linkage to a source purchase_id
        source_id: Optional[str] = None,
        # ignore legacy callers that may pass source_type
        **_ignore,
    ) -> int:
        """
        Grant vendor credit (+amount). Typically used for credit notes from returns.

        Writes a POSITIVE amount into vendor_advances with:
          - source_type='return_credit'
          - source_id = linked purchase_id if provided, else NULL
        """
        if amount <= 0:
            raise ValueError("amount must be positive when granting credit")

        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO vendor_advances (
                    vendor_id, tx_date, amount, source_type, source_id, notes, created_by
                )
                VALUES (?, ?, ?, 'return_credit', ?, ?, ?)
                """,
                (vendor_id, date, float(amount), source_id, notes, created_by),
            )
            return int(cur.lastrowid)

    # ---------- Balances ----------
    def get_balance(self, vendor_id: int) -> float:
        """
        Current credit balance from view v_vendor_advance_balance.
        +ve = you hold credit from the vendor; 0 = none.
        (Negative shouldn't occur under triggers.)
        """
        row = self.conn.execute(
            "SELECT balance FROM v_vendor_advance_balance WHERE vendor_id = ?",
            (vendor_id,),
        ).fetchone()
        if not row:
            return 0.0
        return float(row["balance"] if isinstance(row, sqlite3.Row) else row[0])

    # Alias per spec
    def balance(self, vendor_id: int) -> float:
        return self.get_balance(vendor_id)

    def get_opening_balance(self, vendor_id: int, as_of: str) -> float:
        """
        Opening balance BEFORE a given date: SUM(amount) WHERE tx_date < DATE(as_of).
        Useful for statements with a date range.
        """
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(CAST(amount AS REAL)), 0.0)
            FROM vendor_advances
            WHERE vendor_id = ? AND DATE(tx_date) < DATE(?)
            """,
            (vendor_id, as_of),
        ).fetchone()
        return float(row[0] if row else 0.0)

    # ---------- Ledger / statements ----------
    def list_ledger(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """
        Full ledger for a vendor, filtered by date range if provided.
        Ordered ASC by (tx_date, tx_id).

        Also accepts a tuple/list for date_from as (from, to) when date_to is None,
        for backward compatibility with callers that pass a single tuple.
        Return fields: tx_id, tx_date, amount, source_type, source_id, notes, created_by.
        Statement semantics:
          - source_type='return_credit'        → "Credit Note" (reduces payable)
          - source_type='applied_to_purchase'  → "Credit Applied" to source_id (reduces payable)
        """
        # Back-compat: allow date_from to be a (from, to) tuple/list if date_to not provided
        if isinstance(date_from, (tuple, list)) and len(date_from) == 2 and date_to is None:
            df, dt = date_from
            date_from, date_to = df, dt

        sql = [
            """
            SELECT
              va.tx_id,
              va.tx_date,
              CAST(va.amount AS REAL) AS amount,
              va.source_type,
              va.source_id,
              va.notes,
              va.created_by
            FROM vendor_advances va
            WHERE va.vendor_id = ?
            """
        ]
        params: list[object] = [vendor_id]

        if date_from:
            sql.append("AND DATE(va.tx_date) >= DATE(?)")
            params.append(date_from)
        if date_to:
            sql.append("AND DATE(va.tx_date) <= DATE(?)")
            params.append(date_to)

        sql.append("ORDER BY DATE(va.tx_date) ASC, va.tx_id ASC")
        return self.conn.execute("\n".join(sql), params).fetchall()

    def list_credit_applications_for_purchase(self, purchase_id: str) -> list[dict]:
        """
        All applications of vendor credit against a particular purchase.
        Rows from vendor_advances where source_type='applied_to_purchase' AND source_id=purchase_id.
        """
        return self.conn.execute(
            """
            SELECT
              va.tx_id,
              va.vendor_id,
              va.tx_date,
              CAST(va.amount AS REAL) AS amount,
              va.source_type,
              va.source_id,
              va.notes,
              va.created_by
            FROM vendor_advances va
            WHERE va.source_type = 'applied_to_purchase'
              AND va.source_id = ?
            ORDER BY DATE(va.tx_date) ASC, va.tx_id ASC
            """,
            (purchase_id,),
        ).fetchall()

    def list_credit_notes(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """
        All credit-note entries (source_type='return_credit') for a vendor, optional date range.
        """
        sql = [
            """
            SELECT
              va.tx_id,
              va.tx_date,
              CAST(va.amount AS REAL) AS amount,
              va.source_type,
              va.source_id,
              va.notes,
              va.created_by
            FROM vendor_advances va
            WHERE va.vendor_id = ?
              AND va.source_type = 'return_credit'
            """
        ]
        params: list[object] = [vendor_id]

        if date_from:
            sql.append("AND DATE(va.tx_date) >= DATE(?)")
            params.append(date_from)
        if date_to:
            sql.append("AND DATE(va.tx_date) <= DATE(?)")
            params.append(date_to)

        sql.append("ORDER BY DATE(va.tx_date) ASC, va.tx_id ASC")
        return self.conn.execute("\n".join(sql), params).fetchall()
