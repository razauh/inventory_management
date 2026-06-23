import sqlite3
from decimal import Decimal

import pytest

from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService


@pytest.fixture()
def vendor_cash_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    company_id = conn.execute(
        "INSERT INTO company_info (company_name) VALUES ('Cash Co')"
    ).lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Cash Vendor', 'Test')"
    ).lastrowid
    bank_account_id = conn.execute(
        "INSERT INTO company_bank_accounts (company_id, label) VALUES (?, 'Main Bank')",
        (company_id,),
    ).lastrowid
    vendor_bank_account_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no)
        VALUES (?, 'Vendor Bank', 'Test Bank', 'VB-1')
        """,
        (vendor_id,),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status, paid_amount
        ) VALUES ('PO-CASH', ?, '2026-06-10', 100.0, 'partial', 60.0)
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, bank_account_id,
            vendor_bank_account_id, instrument_type, instrument_no,
            cleared_date, clearing_state
        ) VALUES (
            'PO-CASH', '2026-06-11', 60.0, 'Bank Transfer', ?,
            ?, 'online', 'PAY-60', '2026-06-11', 'cleared'
        )
        """,
        (bank_account_id, vendor_bank_account_id),
    )
    conn.execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, source_id, method,
            bank_account_id, vendor_bank_account_id, instrument_type,
            instrument_no, cleared_date, clearing_state
        ) VALUES (
            ?, '2026-06-11', 25.0, 'deposit', NULL, 'Bank Transfer',
            ?, ?, 'online', 'ADV-25', '2026-06-11', 'cleared'
        )
        """,
        (vendor_id, bank_account_id, vendor_bank_account_id),
    )
    conn.execute(
        """
        INSERT INTO purchase_refunds (
            purchase_id, vendor_id, date, amount, method, bank_account_id,
            vendor_bank_account_id, instrument_type, instrument_no,
            cleared_date, clearing_state
        ) VALUES (
            'PO-CASH', ?, '2026-06-12', 15.0, 'Bank Transfer', ?,
            ?, 'online', 'REF-15', '2026-06-12', 'cleared'
        )
        """,
        (vendor_id, bank_account_id, vendor_bank_account_id),
    )

    try:
        yield conn, int(bank_account_id)
    finally:
        conn.close()


def test_vendor_cash_movements_match_current_reporting_repo(vendor_cash_db):
    conn, _bank_account_id = vendor_cash_db

    rows = list(ReportingRepo(conn).purchase_disbursements_by_day("2026-06-10", "2026-06-12"))
    movements = AccountingService(conn).get_vendor_cash_movements(
        "2026-06-10",
        "2026-06-12",
    )

    assert rows == [
        {
            "date": "2026-06-11",
            "gross_outflow": pytest.approx(60.0),
            "refunds_received": pytest.approx(0.0),
            "net_outflow": pytest.approx(60.0),
        },
        {
            "date": "2026-06-12",
            "gross_outflow": pytest.approx(0.0),
            "refunds_received": pytest.approx(15.0),
            "net_outflow": pytest.approx(-15.0),
        },
    ]
    assert [(row.type, float(row.amount), row.direction) for row in movements] == [
        ("Disbursement", 60.0, "outflow"),
        ("Vendor Advance", 25.0, "outflow"),
        ("Vendor Refund", 15.0, "inflow"),
    ]


def test_bank_ledger_preserves_vendor_payment_advance_and_refund_rows(vendor_cash_db):
    conn, bank_account_id = vendor_cash_db

    rows = AccountingService(conn).get_bank_ledger(
        "2026-06-10",
        "2026-06-12",
        bank_account_id,
    )

    assert [(row.src, float(row.amount_in), float(row.amount_out)) for row in rows] == [
        ("purchase", 0.0, 60.0),
        ("vendor_advance", 0.0, 25.0),
        ("purchase_refund", 15.0, 0.0),
    ]
    assert {row.instrument_no for row in rows} == {"PAY-60", "ADV-25", "REF-15"}


def test_bank_ledger_filters_on_intended_date_basis(vendor_cash_db):
    conn, bank_account_id = vendor_cash_db
    vendor_bank_account_id = conn.execute("SELECT vendor_bank_account_id FROM vendor_bank_accounts LIMIT 1").fetchone()[0]

    # Add a purchase payment with transaction date 2026-06-11 but cleared on 2026-06-15
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, bank_account_id,
            vendor_bank_account_id, instrument_type, instrument_no,
            cleared_date, clearing_state
        ) VALUES (
            'PO-CASH', '2026-06-11', 40.0, 'Bank Transfer', ?,
            ?, 'online', 'PAY-40',
            '2026-06-15', 'cleared'
        )
        """,
        (bank_account_id, vendor_bank_account_id),
    )


    svc = AccountingService(conn)

    # If we filter from 2026-06-14 to 2026-06-16, the entry should be included
    # because it cleared on 2026-06-15.
    rows = svc.get_bank_ledger("2026-06-14", "2026-06-16", bank_account_id)
    assert len(rows) == 1
    assert float(rows[0].amount_out) == 40.0
    assert rows[0].date == "2026-06-15"

    # If we filter from 2026-06-10 to 2026-06-12, this new entry should NOT be included
    # (even though transaction date is 2026-06-11, it cleared outside this window)
    rows_old = svc.get_bank_ledger("2026-06-10", "2026-06-12", bank_account_id)
    assert not any(float(row.amount_out) == 40.0 for row in rows_old)


def test_bank_ledger_keeps_account_attribution_for_vendor_overpayment_split(vendor_cash_db):
    conn, bank_account_id = vendor_cash_db
    vendor_bank_account_id = conn.execute("SELECT vendor_bank_account_id FROM vendor_bank_accounts LIMIT 1").fetchone()[0]

    # Create a fresh purchase PO-OVERPAY with remaining due 40.0
    vendor_id = conn.execute("SELECT vendor_id FROM vendors LIMIT 1").fetchone()[0]
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Product')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status, paid_amount
        ) VALUES ('PO-OVERPAY', ?, '2026-06-10', 100.0, 'partial', 60.0)
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-OVERPAY', ?, 1, ?, 100.0, 120.0, 0.0)
        """,
        (product_id, uom_id),
    )

    from inventory_management.modules.accounting import VendorPaymentPayload
    payload = VendorPaymentPayload(
        purchase_id="PO-OVERPAY",
        amount=Decimal("65.00"),
        method="Bank Transfer",
        date="2026-06-11",
        cleared_date="2026-06-11",
        clearing_state="cleared",
        bank_account_id=bank_account_id,
        vendor_bank_account_id=vendor_bank_account_id,
        instrument_type="online",
        instrument_no="SPLIT-1",
        ref_no="REF-SPLIT",
        notes="Split overpayment",
    )

    AccountingService(conn).record_vendor_payment_event(payload)

    # Check the bank ledger for this account in the window 2026-06-10 to 2026-06-12
    # We should see both rows:
    # 1) purchase payment of 40.0
    # 2) vendor_advance of 25.0
    # Both must have bank_account_id = bank_account_id and instrument_no = 'SPLIT-1'
    rows = AccountingService(conn).get_bank_ledger(
        "2026-06-10",
        "2026-06-12",
        bank_account_id,
    )

    split_payment_rows = [row for row in rows if row.instrument_no == "SPLIT-1"]
    assert len(split_payment_rows) == 2

    purchase_row = [r for r in split_payment_rows if r.src == "purchase"][0]
    advance_row = [r for r in split_payment_rows if r.src == "vendor_advance"][0]

    assert float(purchase_row.amount_out) == pytest.approx(40.0)
    assert purchase_row.bank_account_id == bank_account_id
    assert purchase_row.vendor_bank_account_id == vendor_bank_account_id
    assert purchase_row.method == "Bank Transfer"
    assert purchase_row.instrument_type == "online"

    assert float(advance_row.amount_out) == pytest.approx(25.0)
    assert advance_row.bank_account_id == bank_account_id
    assert advance_row.vendor_bank_account_id == vendor_bank_account_id
    assert advance_row.method == "Bank Transfer"
    assert advance_row.instrument_type == "online"


