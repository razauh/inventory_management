from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtCore import QDate

from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.financial_reports import FinancialReports
from inventory_management.modules.reporting.payment_reports import PaymentReportsTab


@pytest.fixture()
def disbursements_refund_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
        ("Refund Vendor", "test@example.com"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, notes, created_by
        ) VALUES ('PO-REFUND', ?, '2026-06-10', 100.0, 0.0, 'partial', 0.0, 0.0, NULL, NULL)
        """,
        (int(vendor_id),),
    )
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, bank_account_id,
            vendor_bank_account_id, instrument_type, instrument_no,
            instrument_date, deposited_date, cleared_date, clearing_state,
            ref_no, notes, created_by
        ) VALUES ('PO-REFUND', '2026-06-11', 100.0, 'Cash', NULL, NULL, NULL, NULL, NULL, NULL, '2026-06-11', 'cleared', NULL, NULL, NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO purchase_refunds (
            purchase_id, vendor_id, date, amount, method, cleared_date, clearing_state
        ) VALUES ('PO-REFUND', ?, '2026-06-12', 15.0, 'Cash', '2026-06-12', 'cleared')
        """,
        (int(vendor_id),),
    )
    try:
        yield conn
    finally:
        conn.close()


def test_purchase_disbursements_split_gross_refunds_and_net(app, disbursements_refund_db) -> None:
    repo = ReportingRepo(disbursements_refund_db)
    rows = list(repo.purchase_disbursements_by_day("2026-06-10", "2026-06-12"))

    assert [dict(row) for row in rows] == [
        {
            "date": "2026-06-11",
            "gross_outflow": 100.0,
            "refunds_received": 0.0,
            "net_outflow": 100.0,
        },
        {
            "date": "2026-06-12",
            "gross_outflow": 0.0,
            "refunds_received": 15.0,
            "net_outflow": -15.0,
        },
    ]

    cash = FinancialReports(disbursements_refund_db).cash_collections_disbursements("2026-06-10", "2026-06-12")
    assert cash["total_disbursements"] == pytest.approx(85.0)
    assert cash["disbursements"][0]["gross_outflow"] == pytest.approx(100.0)
    assert cash["disbursements"][1]["refunds_received"] == pytest.approx(15.0)

    tab = PaymentReportsTab(disbursements_refund_db)
    tab.dt_from.setDate(QDate.fromString("2026-06-10", "yyyy-MM-dd"))
    tab.dt_to.setDate(QDate.fromString("2026-06-12", "yyyy-MM-dd"))
    tab.refresh()
    disb_rows = tab._rows_disb
    assert disb_rows[0]["gross_outflow"] == pytest.approx(100.0)
    assert disb_rows[0]["net_outflow"] == pytest.approx(100.0)
    assert disb_rows[1]["refunds_received"] == pytest.approx(15.0)
    assert disb_rows[1]["net_outflow"] == pytest.approx(-15.0)
