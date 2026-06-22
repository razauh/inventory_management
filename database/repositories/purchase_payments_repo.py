from __future__ import annotations
import sqlite3
from decimal import Decimal
from typing import Optional

from modules.accounting import AccountingService, VendorPaymentPayload


class PurchasePaymentsRepo:
    METHODS = {"Cash", "Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit", "Other"}

    def __init__(self, conn: sqlite3.Connection):
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
        temp_vendor_bank_name: Optional[str] = None,
        temp_vendor_bank_number: Optional[str] = None,
    ) -> int:
        """
        Insert one row into purchase_payments.
        amount > 0 => payment to vendor.
        Only 'cleared' rows roll into header totals via DB triggers.
        If a positive payment exceeds amount due, convert the excess to vendor credit.
        """
        result = AccountingService(self.conn).record_vendor_payment_event(
            VendorPaymentPayload(
                purchase_id=purchase_id,
                amount=Decimal(str(amount)),
                method=method,
                bank_account_id=bank_account_id,
                vendor_bank_account_id=vendor_bank_account_id,
                instrument_type=instrument_type,
                instrument_no=instrument_no,
                instrument_date=instrument_date,
                deposited_date=deposited_date,
                cleared_date=cleared_date,
                clearing_state=clearing_state,
                ref_no=ref_no,
                notes=notes,
                date=date,
                created_by=created_by,
                temp_vendor_bank_name=temp_vendor_bank_name,
                temp_vendor_bank_number=temp_vendor_bank_number,
            )
        )
        # Note: This method does not commit; caller is responsible for transaction management
        return int(result.payment_id or result.credit_tx_id)

    def update_clearing_state(
        self,
        payment_id: int,
        *,
        clearing_state: str,
        cleared_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> int:
        """Update clearing status for a payment. This method does not commit."""
        return AccountingService(self.conn).update_vendor_payment_state(
            payment_id,
            clearing_state=clearing_state,
            cleared_date=cleared_date,
            notes=notes,
        )

    def list_payments(self, purchase_id: str) -> list[dict]:
        """List all cash movements (payments and refunds) for a purchase, ordered by date then id."""
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

    def list_payments_for_vendor(
        self,
        vendor_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """
        Join purchase_payments -> purchases to list all cash movements for a vendor.
        Fields: payment_id, date, amount, method, instrument_type, instrument_no,
        bank_account_id, vendor_bank_account_id, clearing_state, ref_no, notes, purchase_id.
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
        """Alias of list_payments(purchase_id) for statement drilldowns."""
        return self.list_payments(purchase_id)

    def get_latest_payment_for_purchase(self, purchase_id: str) -> dict | None:
        """
        Get the latest payment details for a specific purchase.
        """
        from ...modules.accounting import AccountingService

        payments = AccountingService(self.conn).get_purchase_payment_history(purchase_id)
        latest = max(payments, key=lambda payment: payment.payment_id, default=None)
        if latest is None:
            return None
        return {
            "amount": float(latest.amount),
            "method": latest.method,
            "date": latest.date,
            "bank_account_id": latest.bank_account_id,
            "vendor_bank_account_id": latest.vendor_bank_account_id,
            "instrument_type": latest.instrument_type,
            "instrument_no": latest.instrument_no,
            "instrument_date": latest.instrument_date,
            "deposited_date": latest.deposited_date,
            "cleared_date": latest.cleared_date,
            "ref_no": latest.ref_no,
            "notes": latest.notes,
            "clearing_state": latest.clearing_state,
            "bank_account_label": latest.bank_account_label,
            "vendor_bank_account_label": latest.vendor_bank_account_label,
        }
