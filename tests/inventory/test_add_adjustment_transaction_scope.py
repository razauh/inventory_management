import sqlite3

import pytest

from inventory_management.database.repositories.inventory_repo import InventoryRepo
from inventory_management.database.schema import SQL


@pytest.fixture()
def adjustment_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Adjustment Vendor', 'Test')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Adjustment Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-ADJ', ?, '2026-01-01', 50, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-ADJ', ?, 5, ?, 10, 12, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 5, ?, 'purchase', 'purchases', 'PO-ADJ', ?, '2026-01-01', 10)
        """,
        (product_id, uom_id, item_id),
    )
    conn.commit()

    try:
        yield conn, int(product_id), int(uom_id)
    finally:
        conn.close()


def test_add_adjustment_preserves_outer_transaction_boundary(adjustment_db):
    conn, product_id, uom_id = adjustment_db
    repo = InventoryRepo(conn)

    conn.execute("BEGIN")
    repo.add_adjustment(
        product_id=product_id,
        uom_id=uom_id,
        quantity=1,
        date="2026-01-02",
        notes="temp adjustment",
    )

    assert conn.in_transaction is True

    conn.rollback()

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM inventory_transactions WHERE transaction_type = 'adjustment'"
    ).fetchone()["c"]
    assert count == 0


def test_add_adjustment_commits_when_used_standalone(adjustment_db):
    conn, product_id, uom_id = adjustment_db
    repo = InventoryRepo(conn)

    repo.add_adjustment(
        product_id=product_id,
        uom_id=uom_id,
        quantity=1,
        date="2026-01-02",
        notes="standalone adjustment",
    )

    assert conn.in_transaction is False

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM inventory_transactions WHERE transaction_type = 'adjustment'"
    ).fetchone()["c"]
    assert count == 1
