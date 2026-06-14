import sqlite3
from types import SimpleNamespace

from inventory_management.database.repositories.products_repo import ProductsRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.product.controller import ProductController


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    base_uom_id = conn.execute(
        "INSERT INTO uoms (unit_name) VALUES ('Piece')"
    ).lastrowid
    alt_uom_id = conn.execute(
        "INSERT INTO uoms (unit_name) VALUES ('Box')"
    ).lastrowid
    conn.commit()
    return conn, int(base_uom_id), int(alt_uom_id)


def test_products_repo_create_preserves_outer_transaction_and_commits_standalone():
    conn, _base_uom_id, _alt_uom_id = make_db()
    repo = ProductsRepo(conn)

    conn.execute("BEGIN")
    product_id = repo.create("Widget", None, None, 1)
    assert conn.in_transaction is True
    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) AS c FROM products WHERE product_id = ?",
        (product_id,),
    ).fetchone()["c"] == 0

    product_id = repo.create("Widget", None, None, 1)
    assert conn.in_transaction is False
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM products WHERE product_id = ?",
        (product_id,),
    ).fetchone()["c"] == 1
    conn.close()


def test_product_controller_add_rolls_back_partial_write_when_later_step_fails(monkeypatch):
    conn, base_uom_id, _alt_uom_id = make_db()
    controller = ProductController.__new__(ProductController)
    controller.conn = conn
    controller.repo = ProductsRepo(conn)
    controller.view = SimpleNamespace()
    controller._reload = lambda: None

    payload = {
        "product": {"name": "Widget", "description": None, "category": None, "min_stock_level": 1},
        "uoms": {
            "base_uom": {"uom_id": base_uom_id},
            "enabled_sales": True,
            "sales_alts": [{"uom_id": 9999, "factor_to_base": 10}],
        },
    }

    class FakeProductForm:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return True

        def payload(self):
            return payload

    messages = []
    monkeypatch.setattr("inventory_management.modules.product.controller.ProductForm", FakeProductForm)
    monkeypatch.setattr("inventory_management.modules.product.controller.info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "inventory_management.modules.product.controller.error",
        lambda _parent, title, text: messages.append((title, text)),
    )

    controller._add()

    assert conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM product_uoms").fetchone()["c"] == 0
    assert messages
    conn.close()


def test_product_controller_edit_rolls_back_earlier_changes_when_later_step_fails(monkeypatch):
    conn, base_uom_id, alt_uom_id = make_db()
    repo = ProductsRepo(conn)
    product_id = repo.create("Widget", "Old", "Cat", 1)
    repo.set_base_uom(product_id, base_uom_id)

    controller = ProductController.__new__(ProductController)
    controller.conn = conn
    controller.repo = repo
    controller.view = SimpleNamespace()
    controller._reload = lambda: None
    controller._selected_id = lambda: product_id

    payload = {
        "product": {"name": "Widget Changed", "description": "New", "category": "Cat 2", "min_stock_level": 5},
        "uoms": {
            "base_uom": {"uom_id": alt_uom_id},
            "enabled_sales": True,
            "sales_alts": [{"uom_id": 9999, "factor_to_base": 12}],
        },
    }

    class FakeProductForm:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return True

        def payload(self):
            return payload

    messages = []
    monkeypatch.setattr("inventory_management.modules.product.controller.ProductForm", FakeProductForm)
    monkeypatch.setattr("inventory_management.modules.product.controller.info", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "inventory_management.modules.product.controller.error",
        lambda _parent, title, text: messages.append((title, text)),
    )

    controller._edit()

    row = conn.execute(
        "SELECT name, description, category, min_stock_level FROM products WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    assert dict(row) == {
        "name": "Widget",
        "description": "Old",
        "category": "Cat",
        "min_stock_level": 1,
    }
    base_row = conn.execute(
        "SELECT uom_id FROM product_uoms WHERE product_id = ? AND is_base = 1",
        (product_id,),
    ).fetchone()
    assert base_row["uom_id"] == base_uom_id
    assert messages
    conn.close()
