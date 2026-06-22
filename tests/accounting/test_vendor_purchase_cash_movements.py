import sqlite3

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
