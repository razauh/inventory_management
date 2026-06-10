import logging
import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from inventory_management.modules.inventory import stock_valuation


def _connection_with_products(products=()):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    conn.executemany("INSERT INTO products (name) VALUES (?)", [(name,) for name in products])
    return conn


def _app():
    return QApplication.instance() or QApplication([])


def _raise_dialog_error(*_args, **_kwargs):
    raise RuntimeError("dialog failed")


def test_duplicate_product_dialog_failure_is_logged(monkeypatch, caplog):
    app = _app()
    conn = _connection_with_products(("Duplicate", "Duplicate"))
    monkeypatch.setattr(stock_valuation.ui, "info", _raise_dialog_error)

    try:
        with caplog.at_level(logging.WARNING, logger=stock_valuation.__name__):
            widget = stock_valuation.StockValuationWidget(conn)
        widget.close()
    finally:
        conn.close()

    assert "Failed to show duplicate product names info dialog" in caplog.text
    assert "dialog failed" in caplog.text
    assert app is QApplication.instance()


def test_not_found_dialog_failure_is_logged(monkeypatch, caplog):
    app = _app()
    conn = _connection_with_products()
    widget = stock_valuation.StockValuationWidget(conn)
    widget.txt_product.setText("Missing product")
    monkeypatch.setattr(stock_valuation.ui, "info", _raise_dialog_error)

    try:
        with caplog.at_level(logging.WARNING, logger=stock_valuation.__name__):
            widget._refresh_clicked()
    finally:
        widget.close()
        conn.close()

    assert "Failed to show 'Product not found' dialog" in caplog.text
    assert "dialog failed" in caplog.text
    assert app is QApplication.instance()
