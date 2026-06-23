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
    PurchaseReturnPayload,
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


def test_purchase_returnable_qty_can_exceed_stock_but_write_path_blocks(
    purchase_return_valuation_db,
):
    conn, ids = purchase_return_valuation_db
    repo = _create_purchase(conn, ids)
    items = repo.list_items("PO-RETURN-VALUATION")
    item_a_id = int(items[0]["item_id"])
    product_a_id = ids["product_a"]

    # Sell some of Product A to reduce physical stock-on-hand
    # Available base stock was 6.0 (from purchase)
    # Let's adjust it down by 4.0, leaving 2.0 on hand
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id,
            date, txn_seq, notes, created_by
        )
        VALUES (?, -4.0, ?, 'adjustment', NULL, NULL, NULL, '2026-06-22', 50, 'Test Adjustment', NULL)
        """,
        (product_a_id, ids["uom_id"]),
    )

    # Rebuild valuations
    from inventory_management.database.repositories.inventory_repo import (
        rebuild_dirty_valuations,
    )

    rebuild_dirty_valuations(conn, product_a_id)

    # Verify stock on hand of Product A is 2.0
    stock_row = conn.execute(
        "SELECT qty_in_base FROM v_stock_on_hand WHERE product_id=?",
        (product_a_id,),
    ).fetchone()
    assert float(stock_row["qty_in_base"]) == pytest.approx(2.0)

    # 1) Read path: with stock_aware=False, we still have contractual returnable = 6.0
    service = AccountingService(conn)
    ret_quantities_contract = service.get_purchase_returnable_quantities(
        "PO-RETURN-VALUATION", stock_aware=False
    )
    assert float(ret_quantities_contract[item_a_id]) == pytest.approx(6.0)

    # 2) Write path: trying to return 5.0 units should fail because only 2.0 are on hand
    with pytest.raises(ValueError, match="only 2.00 available in stock"):
        service.record_purchase_return_event(
            PurchaseReturnPayload(
                purchase_id="PO-RETURN-VALUATION",
                date="2026-06-23",
                created_by=None,
                lines=({"item_id": item_a_id, "qty_return": 5.0},),
                notes="Too many units",
                settlement=None,
            )
        )


def test_purchase_returnable_quantities_expose_stock_aware_value(
    purchase_return_valuation_db,
):
    conn, ids = purchase_return_valuation_db
    repo = _create_purchase(conn, ids)
    items = repo.list_items("PO-RETURN-VALUATION")
    item_a_id = int(items[0]["item_id"])
    product_a_id = ids["product_a"]

    # Sell some of Product A to reduce physical stock-on-hand to 2.0
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id,
            date, txn_seq, notes, created_by
        )
        VALUES (?, -4.0, ?, 'adjustment', NULL, NULL, NULL, '2026-06-22', 50, 'Test Adjustment', NULL)
        """,
        (product_a_id, ids["uom_id"]),
    )

    # Rebuild valuations
    from inventory_management.database.repositories.inventory_repo import (
        rebuild_dirty_valuations,
    )

    rebuild_dirty_valuations(conn, product_a_id)

    # Read path with stock_aware=True should return 2.0 instead of 6.0
    service = AccountingService(conn)
    ret_quantities_stock = service.get_purchase_returnable_quantities(
        "PO-RETURN-VALUATION", stock_aware=True
    )
    assert float(ret_quantities_stock[item_a_id]) == pytest.approx(2.0)

