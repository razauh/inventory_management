from __future__ import annotations

import sqlite3

from inventory_management.database.repositories.inventory_repo import InventoryRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.inventory.stock_valuation import StockValuationWidget


def _valuation_widget_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    no_history_id = conn.execute(
        "INSERT INTO products (name) VALUES ('No History Product')"
    ).lastrowid
    zero_stock_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Zero Stock Product')"
    ).lastrowid

    conn.executemany(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        [
            (no_history_id, uom_id),
            (zero_stock_id, uom_id),
        ],
    )
    conn.execute(
        """
        INSERT INTO stock_valuation_history (
            product_id, valuation_date, quantity, unit_value, total_value, valuation_method
        ) VALUES (?, '2026-01-01', 0, 7, 0, 'moving_average')
        """,
        (zero_stock_id,),
    )
    return conn, int(zero_stock_id)


def test_stock_valuation_widget_shows_distinct_status_states(qtbot, monkeypatch):
    conn, zero_stock_id = _valuation_widget_db()
    try:
        widget = StockValuationWidget(conn)
        qtbot.addWidget(widget)

        assert widget.lbl_status.text() == "Select a product"
        assert widget.val_on_hand.text() == "—"

        widget.txt_product.setText("No History Product")
        widget._on_filters_changed()

        assert widget.lbl_status.text() == "No inventory history"
        assert widget.val_on_hand.text() == "—"
        assert widget.val_unit_value.text() == "—"
        assert widget.val_total_value.text() == "—"

        widget.txt_product.setText("Zero Stock Product")
        widget._on_filters_changed()

        assert widget.lbl_status.text() == "Snapshot loaded"
        assert widget.val_on_hand.text() == "0.00 Piece"
        assert widget.val_unit_value.text() == "7.00"
        assert widget.val_total_value.text() == "0.00"

        seen = {}

        def _fake_info(*args):
            seen["args"] = args

        repo = InventoryRepo(conn)
        widget.repo = repo
        monkeypatch.setattr(
            "inventory_management.modules.inventory.stock_valuation.ui.info",
            _fake_info,
        )
        monkeypatch.setattr(
            repo,
            "stock_on_hand",
            lambda _product_id: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        widget._load_product_snapshot(zero_stock_id)

        assert seen["args"][1] == "Error"
        assert "Failed to load stock snapshot: boom" in seen["args"][2]
        assert widget.lbl_status.text() == "Snapshot unavailable"
        assert widget.val_on_hand.text() == "—"
        assert widget.val_unit_value.text() == "—"
        assert widget.val_total_value.text() == "—"
    finally:
        conn.close()
