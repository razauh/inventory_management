import sqlite3

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService
from inventory_management.modules.purchase.controller import PurchaseController


def _payment_summary_db():
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
    conn.execute("INSERT INTO company_info (company_id, company_name) VALUES (1, 'Company')")
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'Contact')"
    ).lastrowid
    company_bank_id = conn.execute(
        """
        INSERT INTO company_bank_accounts (label, bank_name, account_no)
        VALUES ('Main Bank', 'Bank', '111')
        """
    ).lastrowid
    vendor_bank_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no)
        VALUES (?, 'Vendor Bank', 'Bank', '222')
        """,
        (vendor_id,),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status
        ) VALUES ('PO-SUMMARY', ?, '2026-06-10', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-SUMMARY', ?, 1, ?, 100, 120, 0)
        """,
        (product_id, uom_id),
    )
    return conn, int(company_bank_id), int(vendor_bank_id)


def _bank_payment(repo, company_bank_id, vendor_bank_id, *, amount, date, instrument_no):
    return repo.record_payment(
        purchase_id="PO-SUMMARY",
        amount=amount,
        method="Bank Transfer",
        bank_account_id=company_bank_id,
        vendor_bank_account_id=vendor_bank_id,
        instrument_type="online",
        instrument_no=instrument_no,
        instrument_date=date,
        deposited_date=None,
        cleared_date=date,
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date=date,
        created_by=None,
    )


def test_purchase_payment_summary_matches_current_controller_values():
    conn, company_bank_id, vendor_bank_id = _payment_summary_db()
    empty = AccountingService(conn).get_purchase_payment_summary("PO-SUMMARY")
    assert empty.latest_payment is None
    assert empty.to_detail_payload() is None

    repo = PurchasePaymentsRepo(conn)
    _bank_payment(
        repo,
        company_bank_id,
        vendor_bank_id,
        amount=25,
        date="2026-06-10",
        instrument_no="TX-1",
    )
    _bank_payment(
        repo,
        company_bank_id,
        vendor_bank_id,
        amount=30,
        date="2026-06-11",
        instrument_no="TX-2",
    )
    controller = PurchaseController.__new__(PurchaseController)
    controller.accounting = AccountingService(conn)

    summary = AccountingService(conn).get_purchase_payment_summary("PO-SUMMARY")

    assert controller._latest_purchase_payment("PO-SUMMARY") == {
        "payment_id": summary.latest_payment.payment_id,
        "date": "2026-06-11",
        "method": "Bank Transfer",
        "amount": 30.0,
        "status": "cleared",
    }
    assert controller._overpayment_credited("PO-SUMMARY") == pytest.approx(0.0)
    assert float(summary.paid_amount) == pytest.approx(55)
    assert float(summary.applied_credit) == pytest.approx(0)
    assert float(summary.remaining_due) == pytest.approx(45)
    assert summary.status == "partial"
    assert summary.latest_payment.bank_account_label == "Main Bank"
    assert summary.latest_payment.vendor_bank_account_label == "Vendor Bank"
    assert [
        row.instrument_no
        for row in AccountingService(conn).get_purchase_payment_history("PO-SUMMARY")
    ] == ["TX-1", "TX-2"]
    conn.close()


def test_purchase_payment_summary_preserves_overpayment_credit():
    conn, _company_bank_id, _vendor_bank_id = _payment_summary_db()
    repo = PurchasePaymentsRepo(conn)
    repo.record_payment(
        purchase_id="PO-SUMMARY",
        amount=125,
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

    summary = AccountingService(conn).get_purchase_payment_summary("PO-SUMMARY")

    assert float(summary.latest_payment.amount) == pytest.approx(100)
    assert float(summary.overpayment_credited) == pytest.approx(25)
    assert summary.to_detail_payload() == {
        "method": "Cash",
        "amount": 100.0,
        "status": "cleared",
        "overpayment": 25.0,
        "counterparty_label": "Vendor",
    }
    conn.close()
