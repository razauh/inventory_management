from __future__ import annotations

import sqlite3

from PySide6.QtCore import QDate

from inventory_management.modules.inventory.transactions import TransactionsView


def _temp_inventory_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE uoms (
            uom_id INTEGER PRIMARY KEY,
            unit_name TEXT NOT NULL
        );
        CREATE TABLE inventory_transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity NUMERIC NOT NULL,
            uom_id INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            reference_table TEXT,
            reference_id TEXT,
            reference_item_id INTEGER,
            date DATE NOT NULL,
            posted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            txn_seq INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_by INTEGER
        );
        INSERT INTO products (product_id, name) VALUES (1, 'Widget');
        INSERT INTO uoms (uom_id, unit_name) VALUES (1, 'Each');
        """
    )
    return conn


def test_transactions_view_defaults_to_no_date_filter(qtbot, tmp_path):
    conn = _temp_inventory_db(tmp_path / "inventory_transactions.sqlite")
    today = QDate.currentDate().toString("yyyy-MM-dd")
    conn.executemany(
        """
        INSERT INTO inventory_transactions
            (product_id, quantity, uom_id, transaction_type, date, txn_seq, notes)
        VALUES
            (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (1, 5, 1, "purchase", "2001-01-01", 10, "old row"),
            (1, 2, 1, "sale", today, 20, "today row"),
        ],
    )

    view = TransactionsView(conn)
    qtbot.addWidget(view)

    assert view.date_from_str is None
    assert view.date_to_str is None
    assert view.tbl_txn.model().rowCount() == 2
    assert "no date or product filter" in view.lbl_filter_summary.text()
