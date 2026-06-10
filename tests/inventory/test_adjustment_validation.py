import sqlite3

import pytest

from inventory_management.database.repositories.inventory_repo import DomainError, InventoryRepo
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

    try:
        yield conn, int(product_id), int(uom_id)
    finally:
        conn.close()


def test_add_adjustment_rejects_zero_quantity(adjustment_db):
    conn, product_id, uom_id = adjustment_db

    with pytest.raises(DomainError, match="non-zero"):
        InventoryRepo(conn).add_adjustment(
            product_id=product_id,
            uom_id=uom_id,
            quantity=0,
            date="2026-01-02",
        )

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM inventory_transactions WHERE transaction_type = 'adjustment'"
    ).fetchone()["c"]
    assert count == 0


def test_add_adjustment_rejects_negative_quantity_past_available_stock(adjustment_db):
    conn, product_id, uom_id = adjustment_db

    with pytest.raises(DomainError, match="available stock"):
        InventoryRepo(conn).add_adjustment(
            product_id=product_id,
            uom_id=uom_id,
            quantity=-6,
            date="2026-01-02",
        )

    snapshot = InventoryRepo(conn).stock_on_hand(product_id)
    assert snapshot["on_hand_qty"] == pytest.approx(5.0)


def test_adjustment_trigger_blocks_zero_and_overdrawn_direct_inserts(adjustment_db):
    conn, product_id, uom_id = adjustment_db

    with pytest.raises(sqlite3.IntegrityError, match="non-zero"):
        conn.execute(
            """
            INSERT INTO inventory_transactions (
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id, date, txn_seq
            ) VALUES (?, 0, ?, 'adjustment', NULL, NULL, NULL, '2026-01-02', 20)
            """,
            (product_id, uom_id),
        )

    with pytest.raises(sqlite3.IntegrityError, match="available stock"):
        conn.execute(
            """
            INSERT INTO inventory_transactions (
                product_id, quantity, uom_id, transaction_type,
                reference_table, reference_id, reference_item_id, date, txn_seq
            ) VALUES (?, -6, ?, 'adjustment', NULL, NULL, NULL, '2026-01-02', 20)
            """,
            (product_id, uom_id),
        )


def test_add_adjustment_allows_reduction_up_to_current_stock(adjustment_db):
    conn, product_id, uom_id = adjustment_db

    InventoryRepo(conn).add_adjustment(
        product_id=product_id,
        uom_id=uom_id,
        quantity=-5,
        date="2026-01-02",
    )

    snapshot = InventoryRepo(conn).stock_on_hand(product_id)
    assert snapshot["on_hand_qty"] == pytest.approx(0.0)
