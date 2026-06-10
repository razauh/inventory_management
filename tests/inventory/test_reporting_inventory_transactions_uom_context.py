from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt

from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.inventory_reports import InventoryReports
from inventory_management.modules.reporting.model import InventoryTransactionsTableModel


def _reporting_db() -> tuple[sqlite3.Connection, int]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    base_uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Each')").lastrowid
    alt_uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Box')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Widget')").lastrowid

    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, base_uom_id),
    )
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 0, 12)
        """,
        (product_id, alt_uom_id),
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type, date, txn_seq, notes
        ) VALUES (?, ?, ?, 'adjustment', '2026-06-01', 10, 'box count')
        """,
        (product_id, 2, alt_uom_id),
    )
    return conn, int(product_id)


def test_reporting_repo_returns_raw_and_base_quantity_fields():
    conn, product_id = _reporting_db()
    try:
        rows = ReportingRepo(conn).inventory_transactions("2026-06-01", "2026-06-30", product_id)

        assert len(rows) == 1
        row = rows[0]
        assert float(row["quantity"]) == 2.0
        assert row["unit_name"] == "Box"
        assert float(row["qty_base"]) == 24.0
    finally:
        conn.close()


def test_reporting_transactions_model_shows_qty_uom_and_base_qty():
    conn, product_id = _reporting_db()
    try:
        rows = InventoryReports(conn).transactions("2026-06-01", "2026-06-30", product_id)

        assert rows == [
            {
                "date": "2026-06-01",
                "product_name": "Widget",
                "type": "adjustment",
                "quantity": 2.0,
                "unit_name": "Box",
                "qty_base": 24.0,
                "ref_table": "",
                "ref_id": "",
                "notes": "box count",
            }
        ]

        model = InventoryTransactionsTableModel(rows)
        assert model.HEADERS == (
            "Date",
            "Product",
            "Type",
            "Qty",
            "UoM",
            "Qty (base)",
            "Ref Table",
            "Ref ID",
            "Notes",
        )
        assert model.data(model.index(0, 3), Qt.DisplayRole) == "2"
        assert model.data(model.index(0, 4), Qt.DisplayRole) == "Box"
        assert model.data(model.index(0, 5), Qt.DisplayRole) == "24"
    finally:
        conn.close()
