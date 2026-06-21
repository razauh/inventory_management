import sqlite3
from decimal import Decimal

import pytest

from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import (
    AccountingService,
    PurchaseReturnPreviewLine,
    PurchaseReturnPreviewPayload,
)


@pytest.fixture()
def purchase_return_valuation_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Return Vendor', 'Test')"
    ).lastrowid
    product_a = conn.execute(
        "INSERT INTO products (name) VALUES ('Return Product A')"
    ).lastrowid
    product_b = conn.execute(
        "INSERT INTO products (name) VALUES ('Return Product B')"
    ).lastrowid
    for product_id in (product_a, product_b):
        conn.execute(
            """
            INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
            VALUES (?, ?, 1, 1)
            """,
            (product_id, uom_id),
        )

    try:
        yield conn, {
            "uom_id": int(uom_id),
            "vendor_id": int(vendor_id),
            "product_a": int(product_a),
            "product_b": int(product_b),
        }
    finally:
        conn.close()


def _create_purchase(conn, ids):
    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id="PO-RETURN-VALUATION",
            vendor_id=ids["vendor_id"],
            date="2026-06-21",
            total_amount=0.0,
            order_discount=10.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=None,
        ),
        [
            PurchaseItem(
                None,
                "PO-RETURN-VALUATION",
                ids["product_a"],
                6.0,
                ids["uom_id"],
                10.0,
                15.0,
                1.0,
            ),
            PurchaseItem(
                None,
                "PO-RETURN-VALUATION",
                ids["product_b"],
                4.0,
                ids["uom_id"],
                20.0,
                25.0,
                0.0,
            ),
        ],
    )
    return repo


def test_return_preview_preserves_order_discount_allocation():
    effect = AccountingService().preview_purchase_return_effect(
        PurchaseReturnPreviewPayload(
            lines=(
                PurchaseReturnPreviewLine(
                    quantity=Decimal("6"),
                    purchase_price=Decimal("10"),
                    item_discount=Decimal("1"),
                    return_qty=Decimal("3"),
                ),
                PurchaseReturnPreviewLine(
                    quantity=Decimal("4"),
                    purchase_price=Decimal("20"),
                    item_discount=Decimal("0"),
                    return_qty=Decimal("1.5"),
                ),
            ),
            order_discount=Decimal("10"),
        )
    )

    assert float(effect.value_factor) == pytest.approx(124 / 134)
    assert float(effect.total_qty) == pytest.approx(4.5)
    assert [float(value) for value in effect.line_values] == pytest.approx(
        [27 * 124 / 134, 30 * 124 / 134]
    )
    assert float(effect.total_value) == pytest.approx(57 * 124 / 134)


def test_return_values_match_snapshot_view(purchase_return_valuation_db):
    conn, ids = purchase_return_valuation_db
    repo = _create_purchase(conn, ids)
    items = repo.list_items("PO-RETURN-VALUATION")
    repo.record_return(
        pid="PO-RETURN-VALUATION",
        date="2026-06-22",
        created_by=None,
        lines=[
            {"item_id": int(items[0]["item_id"]), "qty_return": 2.0},
            {"item_id": int(items[1]["item_id"]), "qty_return": 1.0},
        ],
        notes=None,
    )

    view_rows = conn.execute(
        """
        SELECT transaction_id, return_value
        FROM purchase_return_valuations
        WHERE purchase_id = ?
        ORDER BY transaction_id
        """,
        ("PO-RETURN-VALUATION",),
    ).fetchall()
    service_values = AccountingService(conn).get_purchase_return_values(
        "PO-RETURN-VALUATION"
    )
    service_totals = AccountingService(conn).get_purchase_return_totals(
        "PO-RETURN-VALUATION"
    )

    assert [value.transaction_id for value in service_values] == [
        row["transaction_id"] for row in view_rows
    ]
    assert [float(value.return_value) for value in service_values] == pytest.approx(
        [float(row["return_value"]) for row in view_rows]
    )
    assert float(service_totals.qty) == pytest.approx(3.0)
    assert float(service_totals.value) == pytest.approx(
        sum(float(row["return_value"]) for row in view_rows)
    )
