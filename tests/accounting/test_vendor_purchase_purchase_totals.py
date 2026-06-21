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
    PurchaseTotalInputLine,
)


@pytest.fixture()
def purchase_totals_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Totals Vendor', 'Test')"
    ).lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Totals Product')"
    ).lastrowid
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
            "product_id": int(product_id),
        }
    finally:
        conn.close()


def test_purchase_totals_match_purchase_detailed_totals_view(purchase_totals_db):
    conn, ids = purchase_totals_db
    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id="PO-TOTALS",
            vendor_id=ids["vendor_id"],
            date="2026-06-21",
            total_amount=0.0,
            order_discount=3.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=None,
        ),
        [
            PurchaseItem(
                None,
                "PO-TOTALS",
                ids["product_id"],
                2.0,
                ids["uom_id"],
                10.0,
                15.0,
                1.0,
            )
        ],
    )
    item_id = int(repo.list_items("PO-TOTALS")[0]["item_id"])
    repo.record_return(
        pid="PO-TOTALS",
        date="2026-06-21",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 1.0}],
        notes=None,
    )

    expected = conn.execute(
        """
        SELECT
          pdt.subtotal_before_order_discount,
          pdt.order_discount,
          pdt.calculated_total_amount,
          p.total_amount AS stored_total,
          COALESCE(SUM(prv.return_value), 0.0) AS returned_value
        FROM purchase_detailed_totals pdt
        JOIN purchases p ON p.purchase_id = pdt.purchase_id
        LEFT JOIN purchase_return_valuations prv ON prv.purchase_id = pdt.purchase_id
        WHERE pdt.purchase_id = ?
        GROUP BY pdt.purchase_id
        """,
        ("PO-TOTALS",),
    ).fetchone()

    totals = AccountingService(conn).get_purchase_totals("PO-TOTALS")

    assert float(totals.subtotal_before_order_discount) == pytest.approx(
        expected["subtotal_before_order_discount"]
    )
    assert float(totals.order_discount) == pytest.approx(expected["order_discount"])
    assert float(totals.returned_value) == pytest.approx(expected["returned_value"])
    assert float(totals.net_total) == pytest.approx(expected["calculated_total_amount"])
    assert float(totals.stored_total) == pytest.approx(expected["stored_total"])


def test_preview_purchase_total_matches_purchase_form_current_math():
    service = AccountingService()

    totals = service.preview_purchase_total(
        (
            PurchaseTotalInputLine(
                quantity=Decimal("2"),
                purchase_price=Decimal("10"),
                item_discount=Decimal("1"),
            ),
            PurchaseTotalInputLine(
                quantity=Decimal("1"),
                purchase_price=Decimal("5"),
            ),
        ),
        Decimal("3"),
    )
    zero_discount = service.preview_purchase_total(
        (
            PurchaseTotalInputLine(
                quantity=Decimal("2"),
                purchase_price=Decimal("10"),
            ),
        ),
        Decimal("0"),
    )

    assert totals.subtotal_before_order_discount == Decimal("23")
    assert totals.order_discount == Decimal("3")
    assert totals.returned_value == Decimal("0")
    assert totals.net_total == Decimal("20")
    assert zero_discount.net_total == Decimal("20")
