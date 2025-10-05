from __future__ import annotations
import sqlite3
from typing import Optional

from .vendor_advances_repo import VendorAdvancesRepo


class PurchasePaymentsRepo:
    def __init__(self, conn: sqlite3.Connection):
        # ensure rows behave like dicts/tuples
        conn.row_factory = sqlite3.Row
        self.conn = conn

    def record_payment(
        self,
        purchase_id: str,
        *,
        amount: float,
        method: str,
        bank_account_id: Optional[int],
        vendor_bank_account_id: Optional[int],
        instrument_type: Optional[str],
        instrument_no: Optional[str],
        instrument_date: Optional[str],
        deposited_date: Optional[str],
        cleared_date: Optional[str],
        clearing_state: Optional[str],
        ref_no: Optional[str],
        notes: Optional[str],
        date: str,
        created_by: Optional[int],
    ) -> int:
        """
        Insert one row into purchase_payments.

        Notes:
          - amount > 0 => payment to vendor; amount < 0 => refund from vendor.
          - Business rule (cleared-only policy):
              Only rows with clearing_state='cleared' contribute to purchases.paid_amount
              and payment_status via DB triggers. Rows in 'posted', 'pending', or 'bounced'
              states do NOT affect the header totals/status until they become 'cleared'.
          - DB triggers enforce the above rollup and method-specific requirements.
          - No commit here; caller controls the transaction.
          - If amount exceeds the due amount (for positive amounts), the excess is converted to vendor credit.
        """
        # Check if this is an overpayment for a positive amount and convert excess to vendor credit
        if amount > 0:  # Only check for overpayments on positive payments (not refunds)
            # Get purchase information to determine what's due
            purchase_info = self.conn.execute(
                """
                SELECT 
                    p.total_amount, 
                    p.paid_amount, 
                    p.advance_payment_applied,
                    p.vendor_id
                FROM purchases p
                WHERE p.purchase_id = ?
                """,
                (purchase_id,),
            ).fetchone()
            
            if not purchase_info:
                raise ValueError(f"Purchase not found: {purchase_id}")
            
            total_amount = float(purchase_info["total_amount"])
            current_paid = float(purchase_info["paid_amount"])
            current_advance = float(purchase_info["advance_payment_applied"]) if purchase_info["advance_payment_applied"] else 0.0
            vendor_id = int(purchase_info["vendor_id"])
            
            # Calculate amount due (what's left to pay)
            amount_due = total_amount - current_paid - current_advance
            
            # If payment exceeds the amount due, split the payment
            if amount > amount_due + 1e-9:  # Handle overpayment
                # Calculate the excess that needs to be converted to vendor credit
                excess_amount = amount - amount_due
                # Adjust the payment amount to only cover the due amount
                adjusted_amount = amount_due
                
                # Record the excess as a vendor advance (credit)
                if excess_amount > 1e-9:  # Only if there's a meaningful excess
                    vadv = VendorAdvancesRepo(self.conn)
                    vadv.grant_credit(
                        vendor_id=vendor_id,
                        amount=excess_amount,
                        date=date,
                        notes=f"Excess payment converted to credit on {purchase_id}",
                        created_by=created_by,
                        source_id=purchase_id,
                        source_type="overpayment_credit",
                    )
                
                # Use the adjusted amount for the payment (the due amount)
                amount = adjusted_amount

        state = clearing_state or "posted"
        cur = self.conn.execute(
            """
            INSERT INTO purchase_payments (
                purchase_id,
                date,
                amount,
                method,
                bank_account_id,
                vendor_bank_account_id,
                instrument_type,
                instrument_no,
                instrument_date,
                deposited_date,
                cleared_date,
                clearing_state,
                ref_no,
                notes,
                created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                purchase_id,
                date,
                amount,
                method,
                bank_account_id,
                vendor_bank_account_id,
                instrument_type,
                instrument_no,
                instrument_date,
                deposited_date,
                cleared_date,
                state,
                ref_no,
                notes,
                created_by,
            ),
        )
        payment_id = int(cur.lastrowid)
        
        # Audit logging for the payment
        self.conn.execute(
            """
            INSERT INTO audit_logs (user_id, action_type, table_name, record_id, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                created_by,
                "payment",
                "purchase_payments",
                payment_id,
                f"Recorded payment of {amount:g} using {method}. Purchase ID: {purchase_id}",
            ),
        )
        return payment_id

    def update_clearing_state(
        self,
        payment_id: int,
        *,
        clearing_state: str,
        cleared_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Update clearing status for a payment (no commit).
        """
        sets = ["clearing_state = ?"]
        params: list[object] = [clearing_state]

        if cleared_date is not None:
            sets.append("cleared_date = ?")
            params.append(cleared_date)

        if notes is not None:
            sets.append("notes = ?")
            params.append(notes)

        params.append(payment_id)

        sql = f"UPDATE purchase_payments SET {', '.join(sets)} WHERE payment_id = ?"
        cur = self.conn.execute(sql, params)
        return cur.rowcount

    def list_payments(self, purchase_id: str) -> list[dict]:
        """
        List all cash movements (payments and refunds) for a purchase.

        Returns sqlite rows ordered by date then payment_id.
        """
        sql = """
        SELECT
          payment_id,
          purchase_id,
          date,
          CAST(amount AS REAL) AS amount,
          method,
          bank_account_id,
          vendor_bank_account_id,
          instrument_type,
          instrument_no,
          instrument_date,
          deposited_date,
          cleared_date,
          clearing_state,
          ref_no,
          notes,
          created_by
        FROM purchase_payments
        WHERE purchase_id = ?
        ORDER BY DATE(date) ASC, payment_id ASC
        """
        return self.conn.execute(sql, (purchase_id,)).fetchall()

    # -------- New: vendor-scoped statements/reconciliation helpers --------

    def list_payments_for_vendor(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """
        Join purchase_payments -> purchases to list all cash movements for a vendor.
        Fields:
          payment_id, date, amount, method, instrument_type, instrument_no,
          bank_account_id, vendor_bank_account_id, clearing_state, ref_no, notes, purchase_id
        Ordering: DATE(pp.date) ASC, pp.payment_id ASC

        Statement mapping (handled by caller):
          amount > 0 → “Cash Payment” (effect = −amount)
          amount < 0 → “Refund”       (effect = −ABS(amount))
        """
        sql_parts = [
            """
            SELECT
              pp.payment_id,
              pp.date,
              CAST(pp.amount AS REAL) AS amount,
              pp.method,
              pp.instrument_type,
              pp.instrument_no,
              pp.bank_account_id,
              pp.vendor_bank_account_id,
              pp.clearing_state,
              pp.ref_no,
              pp.notes,
              pp.purchase_id
            FROM purchase_payments pp
            JOIN purchases p ON p.purchase_id = pp.purchase_id
            WHERE p.vendor_id = ?
            """
        ]
        params: list[object] = [vendor_id]

        if date_from:
            sql_parts.append("AND DATE(pp.date) >= DATE(?)")
            params.append(date_from)
        if date_to:
            sql_parts.append("AND DATE(pp.date) <= DATE(?)")
            params.append(date_to)

        sql_parts.append("ORDER BY DATE(pp.date) ASC, pp.payment_id ASC")
        sql = "\n".join(sql_parts)
        return self.conn.execute(sql, params).fetchall()

    def list_payments_for_purchase(self, purchase_id: str) -> list[dict]:
        """
        Alias of list_payments(purchase_id) for statement drilldowns.
        """
        return self.list_payments(purchase_id)

    def list_pending_instruments(self, vendor_id: int) -> list[dict]:
        """
        Optional: list rows with clearing_state='pending' for that vendor (via join to purchases).
        Useful for reconciliation reports.
        """
        sql = """
        SELECT
          pp.payment_id,
          pp.date,
          CAST(pp.amount AS REAL) AS amount,
          pp.method,
          pp.instrument_type,
          pp.instrument_no,
          pp.bank_account_id,
          pp.vendor_bank_account_id,
          pp.clearing_state,
          pp.ref_no,
          pp.notes,
          pp.purchase_id
        FROM purchase_payments pp
        JOIN purchases p ON p.purchase_id = pp.purchase_id
        WHERE p.vendor_id = ?
          AND pp.clearing_state = 'pending'
        ORDER BY DATE(pp.date) ASC, pp.payment_id ASC
        """
        return self.conn.execute(sql, (vendor_id,)).fetchall()
