from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt

from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.customer_aging_reports import CustomerAgingReports
from inventory_management.modules.reporting.model import (
    AgingSnapshotTableModel,
    OpenInvoicesTableModel,
    fmt_money,
)


def _customer_aging_db(path: str) -> tuple[sqlite3.Connection, int]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES (?, ?)",
        ("Aging Customer", "test@example.com"),
    ).lastrowid
    sales = [
        ("S-001", "2026-06-01", 100.0, 20.0, 10.0),
        ("S-002", "2026-05-01", 200.0, 50.0, 0.0),
        ("S-003", "2026-03-20", 300.0, 0.0, 25.0),
        ("S-004", "2026-02-01", 400.0, 100.0, 50.0),
    ]
    conn.executemany(
        """
        INSERT INTO sales (
            sale_id, customer_id, date, total_amount, payment_status,
            paid_amount, advance_payment_applied, doc_type
        ) VALUES (?, ?, ?, ?, 'partial', ?, ?, 'sale')
        """,
        [
            (sale_id, customer_id, day, total, paid, advance)
            for sale_id, day, total, paid, advance in sales
        ],
    )
    conn.commit()
    return conn, int(customer_id)


def test_customer_aging_rows_match_shared_table_model_keys(tmp_path):
    conn, customer_id = _customer_aging_db(str(tmp_path / "customer_aging.sqlite"))
    try:
        reports = CustomerAgingReports(conn)

        snapshot_rows = reports.compute_aging_snapshot(
            "2026-06-10",
            include_credit_column=False,
            customer_id=customer_id,
        )
        assert snapshot_rows == [
            {
                "customer_id": customer_id,
                "name": "Aging Customer",
                "total_due": 745.0,
                "b_0_30": 70.0,
                "b_31_60": 150.0,
                "b_61_90": 275.0,
                "b_91_plus": 250.0,
                "available_credit": 0.0,
            }
        ]

        snapshot_model = AgingSnapshotTableModel(snapshot_rows)
        assert [
            snapshot_model.data(snapshot_model.index(0, column), Qt.DisplayRole)
            for column in range(2, 6)
        ] == [
            fmt_money(70.0),
            fmt_money(150.0),
            fmt_money(275.0),
            fmt_money(250.0),
        ]

        invoice_rows = reports.list_open_invoices(customer_id, "2026-06-10")
        assert invoice_rows[0] == {
            "doc_no": "S-004",
            "date": "2026-02-01",
            "total": 400.0,
            "paid": 100.0,
            "advance_applied": 50.0,
            "remaining": 250.0,
            "days_outstanding": 129,
        }

        invoice_model = OpenInvoicesTableModel(invoice_rows)
        assert [
            invoice_model.data(invoice_model.index(0, column), Qt.DisplayRole)
            for column in range(2, 6)
        ] == [fmt_money(400.0), fmt_money(100.0), fmt_money(50.0), fmt_money(250.0)]
    finally:
        conn.close()
