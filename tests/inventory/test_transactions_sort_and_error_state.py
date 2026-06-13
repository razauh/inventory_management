from __future__ import annotations

import sqlite3

from PySide6.QtCore import Qt

from inventory_management.modules.inventory.model import TransactionsTableModel
from inventory_management.modules.inventory.transactions import TransactionsView


def _transactions_db(path):
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
            (1, 5, 1, 'purchase', '2024-01-10', 10, 'later row'),
            (1, 2, 1, 'sale', '2024-01-05', 20, 'earlier row');
        """
    )
    return conn


def test_transactions_table_model_sorts_and_formats_types():
    model = TransactionsTableModel(
        [
            {"transaction_id": 2, "date": "2024-01-10", "transaction_type": "purchase_return", "product": "Widget", "quantity": 1, "unit_name": "Each", "notes": ""},
            {"transaction_id": 1, "date": "2024-01-05", "transaction_type": "sale", "product": "Widget", "quantity": 5, "unit_name": "Each", "notes": ""},
        ]
    )

    assert model.data(model.index(0, 2), Qt.DisplayRole) == "Purchase Return"

    model.sort(0, Qt.AscendingOrder)
    assert model.data(model.index(0, 0), Qt.DisplayRole) == 1

    model.sort(1, Qt.AscendingOrder)
    assert model.data(model.index(0, 1), Qt.DisplayRole) == "2024-01-05"


def test_transactions_view_keeps_last_rows_visible_on_reload_error(qtbot, tmp_path, monkeypatch):
    conn = _transactions_db(tmp_path / "inventory_transactions_error.sqlite")
    view = TransactionsView(conn)
    qtbot.addWidget(view)

    assert view.tbl_txn.model().rowCount() == 2

    calls: list[tuple[str, str]] = []

    def record_info(_parent, title: str, text: str):
        calls.append((title, text))

    monkeypatch.setattr(
        "inventory_management.modules.inventory.transactions.ui.info",
        record_info,
    )

    class _FailingRepo:
        def find_transactions(self, **_kwargs):
            raise RuntimeError("boom")

    view.repo = _FailingRepo()
    view._reload()

    assert calls == [("Error", "Failed to load transactions: boom")]
    assert view.tbl_txn.model().rowCount() == 2
    assert view.lbl_filter_summary.text() == "Load failed. Last successful rows stay visible."
