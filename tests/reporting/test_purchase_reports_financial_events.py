from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtCore import QDate

from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.purchase_reports import PurchaseReportsTab


@pytest.fixture()
def purchase_financial_events_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Event Vendor', 'Test')"
    ).lastrowid
    category = "Widgets"
    product_a = conn.execute(
        "INSERT INTO products (name, category) VALUES ('Event Product A', ?)",
        (category,),
    ).lastrowid
    product_b = conn.execute(
        "INSERT INTO products (name, category) VALUES ('Event Product B', ?)",
        (category,),
    ).lastrowid
    for product_id in (product_a, product_b):
        conn.execute(
            """
            INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
            VALUES (?, ?, 1, 1)
            """,
            (product_id, uom_id),
        )

    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id="PO-EVENTS",
            vendor_id=int(vendor_id),
            date="2026-06-10",
            total_amount=0.0,
            order_discount=10.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=None,
        ),
        [
            PurchaseItem(None, "PO-EVENTS", int(product_a), 6.0, int(uom_id), 10.0, 15.0, 0.0),
            PurchaseItem(None, "PO-EVENTS", int(product_b), 4.0, int(uom_id), 10.0, 15.0, 0.0),
        ],
    )
    item_a = next(row["item_id"] for row in repo.list_items("PO-EVENTS") if row["product_id"] == int(product_a))
    repo.record_return(
        pid="PO-EVENTS",
        date="2026-06-10",
        created_by=None,
        lines=[{"item_id": int(item_a), "qty_return": 3.0}],
        notes="Return from product A",
    )

    try:
        yield conn
    finally:
        conn.close()


def _rows(tab: PurchaseReportsTab, key: str) -> list[dict]:
    tv = tab._tables[key]
    model = tv.model()
    return [model._rows[i] for i in range(model.rowCount())]


def test_purchase_reports_net_item_spend_from_purchase_events(app, purchase_financial_events_db) -> None:
    tab = PurchaseReportsTab(purchase_financial_events_db)
    cutoff = QDate(2026, 6, 10)
    tab.dt_from.setDate(cutoff)
    tab.dt_to.setDate(cutoff)
    tab.refresh()

    by_product = {row["product_name"]: row for row in _rows(tab, "purch_by_product")}
    by_category = _rows(tab, "purch_by_category")[0]
    top_products = _rows(tab, "top_products")

    assert by_product["Event Product A"]["qty_base"] == pytest.approx(6.0)
    assert by_product["Event Product A"]["spend"] == pytest.approx(27.0)
    assert by_product["Event Product B"]["qty_base"] == pytest.approx(4.0)
    assert by_product["Event Product B"]["spend"] == pytest.approx(36.0)
    assert by_category["qty_base"] == pytest.approx(10.0)
    assert by_category["spend"] == pytest.approx(63.0)
    assert top_products[0]["product_name"] == "Event Product B"
    assert top_products[0]["spend"] == pytest.approx(36.0)
    assert top_products[1]["product_name"] == "Event Product A"
    assert top_products[1]["spend"] == pytest.approx(27.0)
