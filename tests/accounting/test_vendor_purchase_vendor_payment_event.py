import sqlite3
from decimal import Decimal

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService, VendorPaymentPayload


def _payment_event_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Product')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status
        ) VALUES ('PO-PAY-EVENT', ?, '2026-06-10', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-PAY-EVENT', ?, 1, ?, 100, 120, 0)
        """,
        (product_id, uom_id),
    )
    return conn


def _payload(amount):
    return VendorPaymentPayload(
        purchase_id="PO-PAY-EVENT",
        amount=Decimal(str(amount)),
        method="Cash",
        date="2026-06-10",
        cleared_date="2026-06-10",
        clearing_state="cleared",
        notes="Payment",
    )


def test_record_vendor_payment_event_matches_purchase_payment_repo():
    conn = _payment_event_db()

    result = AccountingService(conn).record_vendor_payment_event(_payload(40))

    payment = conn.execute(
        """
        SELECT purchase_id, amount, method, clearing_state, notes
        FROM purchase_payments
        WHERE payment_id = ?
        """,
        (result.payment_id,),
    ).fetchone()
    assert payment["purchase_id"] == "PO-PAY-EVENT"
    assert float(payment["amount"]) == pytest.approx(40.0)
    assert payment["method"] == "Cash"
    assert payment["clearing_state"] == "cleared"
    assert payment["notes"] == "Payment"
    assert result.credit_tx_id is None
    assert conn.execute(
        "SELECT paid_amount, payment_status FROM purchases WHERE purchase_id = 'PO-PAY-EVENT'"
    ).fetchone()["paid_amount"] == pytest.approx(40.0)
    assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1
    conn.close()


def test_record_vendor_payment_event_preserves_overpayment_credit():
    conn = _payment_event_db()

    result = AccountingService(conn).record_vendor_payment_event(_payload(125))

    payment = conn.execute("SELECT amount FROM purchase_payments").fetchone()
    credit = conn.execute(
        """
        SELECT amount, source_type, source_id, notes
        FROM vendor_advances
        WHERE tx_id = ?
        """,
        (result.credit_tx_id,),
    ).fetchone()
    assert float(payment["amount"]) == pytest.approx(100.0)
    assert float(credit["amount"]) == pytest.approx(25.0)
    assert credit["source_type"] == "deposit"
    assert credit["source_id"] == "PO-PAY-EVENT"
    assert credit["notes"] == "Excess payment converted to vendor credit on PO-PAY-EVENT"
    conn.close()


def test_purchase_payment_repo_delegates_to_accounting_service():
    conn = _payment_event_db()

    payment_id = PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-PAY-EVENT",
        amount=50,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-10",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-10",
        created_by=None,
    )

    assert conn.execute(
        "SELECT amount FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()[0] == pytest.approx(50.0)
    conn.close()
