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


def test_vendor_overpayment_credit_preserves_bank_metadata():
    conn = _payment_event_db()
    # Add company info
    company_id = conn.execute(
        "INSERT INTO company_info (company_name) VALUES ('Co Name')"
    ).lastrowid
    # Add a company bank account
    bank_account_id = conn.execute(
        "INSERT INTO company_bank_accounts (company_id, label, bank_name, account_no) VALUES (?, 'Co Bank', 'Co Bank', '123')",
        (company_id,)
    ).lastrowid
    # Add a vendor bank account
    vendor_id = conn.execute("SELECT vendor_id FROM vendors LIMIT 1").fetchone()[0]
    vendor_bank_account_id = conn.execute(
        "INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no) VALUES (?, 'Ven Bank', 'Ven Bank', '456')",
        (vendor_id,)
    ).lastrowid

    payload = VendorPaymentPayload(
        purchase_id="PO-PAY-EVENT",
        amount=Decimal("125.00"),
        method="Bank Transfer",
        date="2026-06-10",
        cleared_date="2026-06-10",
        clearing_state="cleared",
        bank_account_id=int(bank_account_id),
        vendor_bank_account_id=int(vendor_bank_account_id),
        instrument_type="online",
        instrument_no="TXN-999",
        instrument_date="2026-06-10",
        ref_no="REF-888",
        temp_vendor_bank_name="Ven Bank Temp",
        temp_vendor_bank_number="456 Temp",
        notes="Payment",
    )

    result = AccountingService(conn).record_vendor_payment_event(payload)

    # Check vendor_advances (the credit row)
    credit = conn.execute(
        """
        SELECT amount, method, bank_account_id, vendor_bank_account_id,
               instrument_type, instrument_no, instrument_date,
               cleared_date, clearing_state, ref_no,
               temp_vendor_bank_name, temp_vendor_bank_number
        FROM vendor_advances
        WHERE tx_id = ?
        """,
        (result.credit_tx_id,),
    ).fetchone()

    assert float(credit["amount"]) == pytest.approx(25.0)
    assert credit["method"] == "Bank Transfer"
    assert credit["bank_account_id"] == bank_account_id
    assert credit["vendor_bank_account_id"] == vendor_bank_account_id
    assert credit["instrument_type"] == "online"
    assert credit["instrument_no"] == "TXN-999"
    assert credit["instrument_date"] == "2026-06-10"
    assert credit["cleared_date"] == "2026-06-10"
    assert credit["clearing_state"] == "cleared"
    assert credit["ref_no"] == "REF-888"
    assert credit["temp_vendor_bank_name"] == "Ven Bank Temp"
    assert credit["temp_vendor_bank_number"] == "456 Temp"

    conn.close()

