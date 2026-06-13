from __future__ import annotations

import sqlite3

from inventory_management.modules.inventory.stock_valuation import StockValuationWidget


def _stock_lookup_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE products (
            product_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        INSERT INTO products (product_id, name) VALUES (1, 'Widget');
        INSERT INTO products (product_id, name) VALUES (2, 'Widget');
        INSERT INTO products (product_id, name) VALUES (3, 'Gadget');
        """
    )
    return conn


def test_stock_valuation_clears_stale_card_for_not_found_and_ambiguous_names(qtbot, tmp_path, monkeypatch):
    conn = _stock_lookup_db(tmp_path / "stock_valuation_lookup.sqlite")
    calls: list[tuple[str, str]] = []

    def record_info(_parent, title: str, text: str):
        calls.append((title, text))

    monkeypatch.setattr(
        "inventory_management.modules.inventory.stock_valuation.ui.info",
        record_info,
    )

    widget = StockValuationWidget(conn)
    qtbot.addWidget(widget)
    calls.clear()

    widget.val_on_hand.setText("12.00 Each")
    widget.val_unit_value.setText("100.00")
    widget.val_total_value.setText("1,200.00")
    widget.lbl_status.setText("Snapshot loaded")

    widget.txt_product.setText("Missing Product")
    widget._refresh_clicked()

    assert calls[-1] == ("Not found", "Product 'Missing Product' was not found.")
    assert widget.lbl_status.text() == "Select a product"
    assert widget.val_on_hand.text() == "—"
    assert widget.val_unit_value.text() == "—"
    assert widget.val_total_value.text() == "—"

    widget.txt_product.setText("Widget")
    widget._refresh_clicked()

    assert calls[-1] == (
        "Ambiguous product",
        "Product 'Widget' matches more than one product. Pick one with its ID.",
    )
    assert widget.lbl_status.text() == "Select a product"
    assert widget.val_on_hand.text() == "—"
    assert widget.val_unit_value.text() == "—"
    assert widget.val_total_value.text() == "—"
