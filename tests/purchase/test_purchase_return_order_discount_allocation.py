import sqlite3

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.schema import SQL


@pytest.fixture()
def purchase_return_discount_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Discount Vendor', 'Test')"
    ).lastrowid
    product_a = conn.execute(
        "INSERT INTO products (name) VALUES ('Discount Product A')"
    ).lastrowid
    product_b = conn.execute(
        "INSERT INTO products (name) VALUES ('Discount Product B')"
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


def _create_purchase(conn, ids, purchase_id, items):
    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id=purchase_id,
            vendor_id=ids["vendor_id"],
            date="2026-06-01",
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
                purchase_id,
                item["product_id"],
                item["quantity"],
                ids["uom_id"],
                item["purchase_price"],
                item["sale_price"],
                item.get("item_discount", 0.0),
            )
            for item in items
        ],
    )
    return repo


def _record_cash_payment(conn, purchase_id, amount):
    PurchasePaymentsRepo(conn).record_payment(
        purchase_id=purchase_id,
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-01",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-01",
        created_by=None,
    )


def _calculated_total(conn, purchase_id):
    row = conn.execute(
        """
        SELECT calculated_total_amount
        FROM purchase_detailed_totals
        WHERE purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    return float(row["calculated_total_amount"])


def test_full_return_allocates_order_discount_and_caps_credit(
    purchase_return_discount_db,
):
    conn, ids = purchase_return_discount_db
    purchase_id = "PO-DISCOUNT-FULL-RETURN"
    repo = _create_purchase(
        conn,
        ids,
        purchase_id,
        [
            {
                "product_id": ids["product_a"],
                "quantity": 10.0,
                "purchase_price": 10.0,
                "sale_price": 12.0,
            }
        ],
    )
    item_id = int(repo.list_items(purchase_id)[0]["item_id"])
    _record_cash_payment(conn, purchase_id, 90.0)

    repo.record_return(
        pid=purchase_id,
        date="2026-06-02",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 10.0}],
        notes="Full discounted return",
        settlement={"mode": "credit_note"},
    )

    return_total = repo.purchase_return_totals(purchase_id)["value"]
    credit_total = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS amount
        FROM vendor_advances
        WHERE source_type = 'return_credit'
          AND source_id = ?
        """,
        (purchase_id,),
    ).fetchone()["amount"]

    assert return_total == pytest.approx(90.0)
    assert _calculated_total(conn, purchase_id) == pytest.approx(0.0)
    assert float(credit_total) == pytest.approx(90.0)


def test_partial_return_uses_returned_quantity_share_of_discounted_line_value(
    purchase_return_discount_db,
):
    conn, ids = purchase_return_discount_db
    purchase_id = "PO-DISCOUNT-PARTIAL-RETURN"
    repo = _create_purchase(
        conn,
        ids,
        purchase_id,
        [
            {
                "product_id": ids["product_a"],
                "quantity": 6.0,
                "purchase_price": 10.0,
                "sale_price": 12.0,
            },
            {
                "product_id": ids["product_b"],
                "quantity": 4.0,
                "purchase_price": 10.0,
                "sale_price": 12.0,
            },
        ],
    )
    item_id = int(repo.list_items(purchase_id)[0]["item_id"])

    repo.record_return(
        pid=purchase_id,
        date="2026-06-02",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 3.0}],
        notes="Partial discounted return",
    )

    return_total = repo.purchase_return_totals(purchase_id)["value"]

    assert return_total == pytest.approx(27.0)
    assert _calculated_total(conn, purchase_id) == pytest.approx(63.0)
