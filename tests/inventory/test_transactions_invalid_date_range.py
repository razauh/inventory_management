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
        INSERT INTO inventory_transactions
            (product_id, quantity, uom_id, transaction_type, date, txn_seq, notes)
        VALUES
            (1, 5, 1, 'purchase', '2024-01-05', 10, 'row 1'),
            (1, 2, 1, 'sale', '2024-01-10', 20, 'row 2');
        """
    )
    return conn


def test_transactions_view_rejects_invalid_date_range(qtbot, tmp_path, monkeypatch):
    conn = _temp_inventory_db(tmp_path / "inventory_transactions_invalid_range.sqlite")
    view = TransactionsView(conn)
    qtbot.addWidget(view)

    calls: list[tuple[str, str]] = []

    def record_info(_parent, title: str, text: str):
        calls.append((title, text))

    monkeypatch.setattr(
        "inventory_management.modules.inventory.transactions.ui.info",
        record_info,
    )

    view.date_from.blockSignals(True)
    view.date_to.blockSignals(True)
    try:
        view.date_from.setDate(QDate(2024, 1, 20))
        view.date_to.setDate(QDate(2024, 1, 10))
    finally:
        view.date_from.blockSignals(False)
        view.date_to.blockSignals(False)

    view._reload()

    assert calls == [
        (
            "Invalid date range",
            "'From' date must be on or before 'To' date.",
        )
    ]
    assert view.tbl_txn.model().rowCount() == 0
    assert view.lbl_filter_summary.text() == "Invalid date range. 'From' must be on or before 'To'."

    view.date_from.setDate(QDate(2024, 1, 1))

    assert calls == [
        (
            "Invalid date range",
            "'From' date must be on or before 'To' date.",
        )
    ]
    assert view.tbl_txn.model().rowCount() == 2
    assert "Showing 2 transaction(s)" in view.lbl_filter_summary.text()
