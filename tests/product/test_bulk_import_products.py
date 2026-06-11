import sqlite3
import sys
from types import SimpleNamespace

import pytest

from inventory_management.database.schema import SQL
from inventory_management.scripts import bulk_import_products as importer


class FakeFrame:
    def __init__(self, rows):
        self.columns = list(importer.REQUIRED_HEADERS)
        self._rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return list(self._rows)


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    conn.commit()
    return conn


def install_fake_pandas(monkeypatch, rows):
    calls = []

    def read_excel(path, **kwargs):
        calls.append((path, kwargs))
        return FakeFrame(rows)

    monkeypatch.setitem(sys.modules, "pandas", SimpleNamespace(read_excel=read_excel))
    return calls


def test_import_products_from_xlsx_uses_pandas_and_imports_uoms(monkeypatch, tmp_path):
    conn = make_db()
    xlsx_path = tmp_path / "products.xlsx"
    xlsx_path.write_bytes(b"placeholder")
    rows = [
        {
            "name": "Bulk Widget",
            "base_unit": "Box",
            "alt_unit": "Piece",
            "Category": "Hardware",
            "Factor": 100,
        }
    ]
    calls = install_fake_pandas(monkeypatch, rows)

    result = importer.import_products_from_xlsx(conn, xlsx_path)

    assert result.imported_count == 1
    assert result.failed_count == 0
    assert calls[0][1]["engine"] == "openpyxl"
    product = conn.execute(
        "SELECT product_id, name, category, min_stock_level FROM products WHERE name = ?",
        ("Bulk Widget",),
    ).fetchone()
    assert dict(product) == {
        "product_id": product["product_id"],
        "name": "Bulk Widget",
        "category": "Hardware",
        "min_stock_level": 0,
    }
    uoms = conn.execute(
        """
        SELECT u.unit_name, pu.is_base, CAST(pu.factor_to_base AS REAL) AS factor_to_base
        FROM product_uoms pu
        JOIN uoms u ON u.uom_id = pu.uom_id
        WHERE pu.product_id = ?
        ORDER BY pu.is_base DESC, u.unit_name
        """,
        (product["product_id"],),
    ).fetchall()
    assert [(row["unit_name"], row["is_base"], row["factor_to_base"]) for row in uoms] == [
        ("Box", 1, 1.0),
        ("Piece", 0, 0.01),
    ]
    conn.close()


def test_import_products_from_xlsx_rejects_duplicate_without_partial_import(monkeypatch, tmp_path):
    conn = make_db()
    conn.execute(
        "INSERT INTO products (name, description, category, min_stock_level) VALUES (?, NULL, NULL, 0)",
        ("Existing Widget",),
    )
    conn.commit()
    xlsx_path = tmp_path / "products.xlsx"
    xlsx_path.write_bytes(b"placeholder")
    rows = [
        {
            "name": "New Widget",
            "base_unit": "Piece",
            "alt_unit": "",
            "Category": "Hardware",
            "Factor": "",
        },
        {
            "name": "Existing Widget",
            "base_unit": "Piece",
            "alt_unit": "",
            "Category": "Hardware",
            "Factor": "",
        },
    ]
    install_fake_pandas(monkeypatch, rows)

    with pytest.raises(importer.ImportValidationError) as excinfo:
        importer.import_products_from_xlsx(conn, xlsx_path)

    assert excinfo.value.failed_count == 1
    assert "duplicate products" in str(excinfo.value)
    names = [
        row["name"]
        for row in conn.execute("SELECT name FROM products ORDER BY product_id").fetchall()
    ]
    assert names == ["Existing Widget"]
    conn.close()


def test_load_xlsx_reports_missing_pandas(monkeypatch, tmp_path):
    monkeypatch.delitem(sys.modules, "pandas", raising=False)

    real_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)

    with pytest.raises(importer.ImportValidationError) as excinfo:
        importer.load_xlsx(tmp_path / "products.xlsx")

    assert "Install pandas and openpyxl" in str(excinfo.value)


def test_product_controller_import_uses_file_dialog_and_refreshes(monkeypatch, tmp_path):
    from inventory_management.modules.product.controller import ProductController

    xlsx_path = tmp_path / "products.xlsx"
    xlsx_path.write_bytes(b"placeholder")
    controller = ProductController.__new__(ProductController)
    controller.conn = object()
    controller.view = SimpleNamespace()
    reloads = []
    messages = []
    controller._reload = lambda: reloads.append(True)

    monkeypatch.setattr(
        "inventory_management.modules.product.controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(xlsx_path), ""),
    )
    monkeypatch.setattr(
        "inventory_management.scripts.bulk_import_products.import_products_from_xlsx",
        lambda conn, path: importer.ImportResult(3, 0, "ok"),
    )
    monkeypatch.setattr(
        "inventory_management.modules.product.controller.info",
        lambda _parent, title, text: messages.append((title, text)),
    )

    controller._import_products()

    assert reloads == [True]
    assert messages == [("Import complete", "Imported products: 3\nSkipped/failed rows: 0")]
