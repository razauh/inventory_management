import sqlite3

import pytest

from inventory_management.database.repositories.inventory_repo import (
    InventoryRepo,
    rebuild_dirty_valuations,
)
from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import SQL


@pytest.fixture()
def ordering_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Ordering Vendor', 'Test')"
    ).lastrowid
    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('Ordering Customer', 'Test')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Ordering Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    try:
        yield conn, int(vendor_id), int(customer_id), int(product_id), int(uom_id)
    finally:
        conn.close()


def _insert_purchase(conn, vendor_id, product_id, uom_id, purchase_id, date, qty, price, seq):
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES (?, ?, ?, ?, 'unpaid')
        """,
        (purchase_id, vendor_id, date, qty * price),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (purchase_id, product_id, qty, uom_id, price, price + 10),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, ?, ?, 'purchase', 'purchases', ?, ?, ?, ?)
        """,
        (product_id, qty, uom_id, purchase_id, item_id, date, seq),
    )
    return int(item_id)


def _create_sale(conn, customer_id, product_id, uom_id, sale_id, date, qty):
    repo = SalesRepo(conn)
    repo.create_sale(
        SaleHeader(
            sale_id=sale_id,
            customer_id=customer_id,
            date=date,
            total_amount=qty * 12,
            order_discount=0,
            payment_status="unpaid",
            paid_amount=0,
            advance_payment_applied=0,
            notes=None,
            created_by=None,
        ),
        [
            SaleItem(
                item_id=None,
                sale_id=sale_id,
                product_id=product_id,
                quantity=qty,
                uom_id=uom_id,
                unit_price=12,
                item_discount=0,
            )
        ],
    )
    return conn.execute(
        "SELECT item_id FROM sale_items WHERE sale_id = ?",
        (sale_id,),
    ).fetchone()["item_id"]


def test_sale_txn_seq_preserves_same_date_rebuild_order(ordering_db):
    conn, vendor_id, customer_id, product_id, uom_id = ordering_db
    date = "2026-01-15"
    _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-SEQ", date, 10, 10, 10)
    _create_sale(conn, customer_id, product_id, uom_id, "SO-SEQ", date, 4)

    rows = conn.execute(
        """
        SELECT transaction_type, txn_seq
        FROM inventory_transactions
        WHERE product_id = ?
        ORDER BY txn_seq, transaction_id
        """,
        (product_id,),
    ).fetchall()
    assert [(row["transaction_type"], row["txn_seq"]) for row in rows] == [
        ("purchase", 10),
        ("sale", 20),
    ]

    conn.execute(
        """
        INSERT INTO valuation_dirty (product_id, earliest_impacted, reason)
        VALUES (?, ?, 'test_rebuild')
        """,
        (product_id, date),
    )
    rebuild_dirty_valuations(conn, product_id)

    snapshot = conn.execute(
        "SELECT qty_in_base, unit_value, total_value FROM v_stock_on_hand WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    assert float(snapshot["qty_in_base"]) == pytest.approx(6.0)
    assert float(snapshot["unit_value"]) == pytest.approx(10.0)
    assert float(snapshot["total_value"]) == pytest.approx(60.0)


def test_sale_return_and_adjustment_receive_next_same_date_txn_seq(ordering_db):
    conn, vendor_id, customer_id, product_id, uom_id = ordering_db
    date = "2026-01-15"
    _insert_purchase(conn, vendor_id, product_id, uom_id, "PO-SEQ", date, 10, 10, 10)
    item_id = _create_sale(conn, customer_id, product_id, uom_id, "SO-SEQ", date, 4)

    SalesRepo(conn).record_return(
        sid="SO-SEQ",
        date=date,
        created_by=None,
        lines=[
            {
                "item_id": item_id,
                "product_id": product_id,
                "uom_id": uom_id,
                "qty_return": 1,
            }
        ],
        notes=None,
    )
    InventoryRepo(conn).add_adjustment(
        product_id=product_id,
        uom_id=uom_id,
        quantity=2,
        date=date,
    )

    rows = conn.execute(
        """
        SELECT transaction_type, txn_seq
        FROM inventory_transactions
        WHERE product_id = ?
        ORDER BY txn_seq, transaction_id
        """,
        (product_id,),
    ).fetchall()
    assert [(row["transaction_type"], row["txn_seq"]) for row in rows] == [
        ("purchase", 10),
        ("sale", 20),
        ("sale_return", 30),
        ("adjustment", 40),
    ]
