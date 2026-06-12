from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtCore import QDate
from PySide6.QtCore import Qt

from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.comprehensive_payments_reports import (
    ComprehensivePaymentReports,
    _DetailedPaymentsTableModel,
    _PaymentSummaryTableModel,
)
from inventory_management.modules.reporting.enhanced_payment_reports import (
    EnhancedPaymentReportsTab,
)


@pytest.fixture()
def payment_reports_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
        ("Refund Vendor", "vendor@example.com"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, notes, created_by
        ) VALUES ('PO-REFUND', ?, '2026-06-10', 100.0, 0.0, 'partial', 100.0, 0.0, NULL, NULL)
        """,
        (int(vendor_id),),
    )
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, cleared_date, clearing_state
        ) VALUES ('PO-REFUND', '2026-06-11', 100.0, 'Cash', '2026-06-11', 'cleared')
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


def test_comprehensive_payment_reports_include_vendor_refunds(payment_reports_db: sqlite3.Connection) -> None:
    reports = ComprehensivePaymentReports(payment_reports_db)

    summary = reports.payments_summary_by_status("2026-06-10", "2026-06-12")
    assert summary == [
        {
            "status": "cleared",
            "type": "Disbursement",
            "count": 1,
            "total_amount": pytest.approx(100.0),
        },
        {
            "status": "cleared",
            "type": "Vendor Refund",
            "count": 1,
            "total_amount": pytest.approx(15.0),
        },
    ]

    detailed = reports.all_payments_detailed("2026-06-10", "2026-06-12")
    assert [row["type"] for row in detailed] == ["Vendor Refund", "Disbursement"]
    assert detailed[0]["amount"] == pytest.approx(15.0)
    assert detailed[1]["amount"] == pytest.approx(100.0)


def test_enhanced_payment_reports_include_vendor_refunds(
    app, qtbot, payment_reports_db: sqlite3.Connection
) -> None:
    tab = EnhancedPaymentReportsTab(payment_reports_db)
    qtbot.addWidget(tab)

    tab.dt_from.setDate(QDate.fromString("2026-06-10", "yyyy-MM-dd"))
    tab.dt_to.setDate(QDate.fromString("2026-06-12", "yyyy-MM-dd"))
    tab.refresh()

    assert [row["type"] for row in tab._rows_all_payments] == ["Disbursement", "Vendor Refund"]
    assert tab._rows_all_payments[1]["amount"] == pytest.approx(15.0)
    assert tab.lbl_all_total.text().endswith("115.00")


def test_comprehensive_payment_models_use_field_keys() -> None:
    summary_rows = [
        {"status": "cleared", "type": "Collection", "count": 2, "total_amount": 125.5}
    ]
    detailed_rows = [
        {
            "date": "2026-06-12",
            "type": "Vendor Refund",
            "amount": 15.0,
            "method": "Cash",
            "status": "cleared",
            "doc_id": "PO-REFUND",
            "notes": "Paid back",
        }
    ]

    summary_model = _PaymentSummaryTableModel(summary_rows)
    assert summary_model.data(summary_model.index(0, 0), Qt.DisplayRole) == "cleared"
    assert summary_model.data(summary_model.index(0, 1), Qt.DisplayRole) == "Collection"
    assert summary_model.data(summary_model.index(0, 2), Qt.DisplayRole) == "2"
    assert summary_model.data(summary_model.index(0, 3), Qt.DisplayRole) == "125.50"

    detailed_model = _DetailedPaymentsTableModel(detailed_rows)
    assert detailed_model.data(detailed_model.index(0, 0), Qt.DisplayRole) == "2026-06-12"
    assert detailed_model.data(detailed_model.index(0, 5), Qt.DisplayRole) == "PO-REFUND"
    assert detailed_model.data(detailed_model.index(0, 2), Qt.DisplayRole) == "15.00"
