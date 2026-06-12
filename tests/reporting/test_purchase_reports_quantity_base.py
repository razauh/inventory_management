from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtCore import QDate

from inventory_management.database.repositories.purchases_repo import PurchasesRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.purchase_reports import PurchaseReportsTab


@pytest.fixture()
def purchase_qty_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    conn.execute("DROP TRIGGER trg_purchase_items_base_only_ins")
    conn.execute("DROP TRIGGER trg_purchase_items_base_only_upd")

    uom_piece = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    uom_carton = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Carton')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Qty Vendor', 'Test')"
    ).lastrowid
    prod_a = conn.execute("INSERT INTO products (name, category) VALUES ('Widget A', 'Widgets')").lastrowid
    prod_b = conn.execute("INSERT INTO products (name, category) VALUES ('Widget B', 'Widgets')").lastrowid
    for product_id, uom_id, is_base, factor_to_base in (
        (prod_a, uom_piece, 1, 1.0),
        (prod_b, uom_carton, 0, 12.0),
    ):
        conn.execute(
            """
            INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
            VALUES (?, ?, ?, ?)
            """,
            (product_id, uom_id, is_base, factor_to_base),
        )

    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, notes, created_by
        ) VALUES ('PO-QTY', ?, '2026-06-10', 30.0, 0.0, 'unpaid', 0.0, 0.0, NULL, NULL)
        """,
        (int(vendor_id),),
    )
    item_piece = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount
        ) VALUES ('PO-QTY', ?, 1.0, ?, 10.0, 15.0, 0.0)
        """,
        (int(prod_a), int(uom_piece)),
    ).lastrowid
    item_carton = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount
        ) VALUES ('PO-QTY', ?, 1.0, ?, 20.0, 30.0, 0.0)
        """,
        (int(prod_b), int(uom_carton)),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 1.0, ?, 'purchase', 'purchases', 'PO-QTY', ?, '2026-06-10', 10)
        """,
        (int(prod_a), int(uom_piece), int(item_piece)),
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 1.0, ?, 'purchase', 'purchases', 'PO-QTY', ?, '2026-06-10', 20)
        """,
        (int(prod_b), int(uom_carton), int(item_carton)),
    )
    PurchasesRepo(conn).record_return(
        pid="PO-QTY",
        date="2026-06-10",
        created_by=None,
        lines=[{"item_id": int(item_carton), "qty_return": 1.0}],
        notes="Returned carton",
    )

    try:
        yield conn
    finally:
        conn.close()


def _rows(tab: PurchaseReportsTab, key: str) -> list[dict]:
    tv = tab._tables[key]
    model = tv.model()
    return [model._rows[i] for i in range(model.rowCount())]


def test_purchase_reports_convert_quantities_to_base(app, purchase_qty_db) -> None:
    tab = PurchaseReportsTab(purchase_qty_db)
    cutoff = QDate(2026, 6, 10)
    tab.dt_from.setDate(cutoff)
    tab.dt_to.setDate(cutoff)
    tab.refresh()

    by_product = {row["product_name"]: row for row in _rows(tab, "purch_by_product")}
    by_category = _rows(tab, "purch_by_category")[0]
    top_products = {row["product_name"]: row for row in _rows(tab, "top_products")}
    returns = {row["metric"]: row["value"] for row in _rows(tab, "returns_summary")}

    assert by_product["Widget A"]["qty_base"] == pytest.approx(1.0)
    assert by_product["Widget B"]["qty_base"] == pytest.approx(12.0)
    assert by_category["qty_base"] == pytest.approx(13.0)
    assert top_products["Widget A"]["qty_base"] == pytest.approx(1.0)
    assert top_products["Widget B"]["qty_base"] == pytest.approx(12.0)
    assert returns["Returned Qty (base)"] == pytest.approx(12.0)
    assert returns["Return Value"] == pytest.approx(20.0)
