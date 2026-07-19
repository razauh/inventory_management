import sqlite3

import pytest

from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService


@pytest.fixture()
def purchase_inventory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Inventory Vendor', 'Test')"
    ).lastrowid
    product_a = conn.execute(
        "INSERT INTO products (name) VALUES ('Inventory Product A')"
    ).lastrowid
    product_b = conn.execute(
        "INSERT INTO products (name) VALUES ('Inventory Product B')"
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
        yield conn, int(vendor_id), int(product_a), int(product_b), int(uom_id)
    finally:
        conn.close()


def _header(vendor_id, purchase_id="PO-INV", date="2026-06-01"):
    return PurchaseHeader(
        purchase_id=purchase_id,
        vendor_id=vendor_id,
        date=date,
        total_amount=0.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes="Inventory note",
        created_by=None,
    )


def _item(product_id, uom_id, qty, purchase_id="PO-INV", item_id=None):
    return PurchaseItem(
        item_id,
        purchase_id,
        product_id,
        qty,
        uom_id,
        10.0,
        12.0,
        0.0,
    )


def _purchase_rows(conn, purchase_id="PO-INV"):
    return conn.execute(
        """
        SELECT
          transaction_id,
          product_id,
          quantity,
          uom_id,
          transaction_type,
          reference_table,
          reference_id,
          reference_item_id,
          date,
          txn_seq,
          notes,
          created_by
        FROM inventory_transactions
        WHERE reference_table = 'purchases'
          AND reference_id = ?
        ORDER BY txn_seq, transaction_id
        """,
        (purchase_id,),
    ).fetchall()


def test_purchase_inventory_event_preserves_transaction_rows(purchase_inventory_db):
    conn, vendor_id, product_a, product_b, uom_id = purchase_inventory_db
    repo = PurchasesRepo(conn)

    repo.create_purchase(
        _header(vendor_id),
        [_item(product_a, uom_id, 5.0), _item(product_b, uom_id, 3.0)],
    )
    created = _purchase_rows(conn)

    assert [(row["transaction_type"], row["txn_seq"]) for row in created] == [
        ("purchase", 10),
        ("purchase", 20),
    ]
    assert [float(row["quantity"]) for row in created] == pytest.approx([5.0, 3.0])
    assert [row["reference_table"] for row in created] == ["purchases", "purchases"]
    assert [row["reference_id"] for row in created] == ["PO-INV", "PO-INV"]
    assert [row["notes"] for row in created] == ["Inventory note", "Inventory note"]

    item_ids = [int(row["item_id"]) for row in repo.list_items("PO-INV")]
    repo.update_purchase(
        _header(vendor_id, date="2026-06-02"),
        [
            _item(product_a, uom_id, 7.0, item_id=item_ids[0]),
            _item(product_b, uom_id, 4.0, item_id=item_ids[1]),
        ],
    )
    updated = _purchase_rows(conn)

    assert [(row["transaction_type"], row["txn_seq"]) for row in updated] == [
        ("purchase", 10),
        ("purchase", 20),
    ]
    assert [float(row["quantity"]) for row in updated] == pytest.approx([7.0, 4.0])
    assert [row["reference_item_id"] for row in updated] == item_ids
    assert [row["date"] for row in updated] == ["2026-06-02", "2026-06-02"]

    repo.delete_purchase("PO-INV")

    assert _purchase_rows(conn) == []
    assert AccountingService(conn).get_inventory_accounting_events(
        "purchases",
        "PO-INV",
    ) == ()


def test_purchase_return_inventory_event_preserves_returnable_quantities_and_sequence(
    purchase_inventory_db,
):
    conn, vendor_id, product_a, product_b, uom_id = purchase_inventory_db
    repo = PurchasesRepo(conn)
    repo.create_purchase(
        _header(vendor_id),
        [_item(product_a, uom_id, 5.0), _item(product_b, uom_id, 3.0)],
    )
    item_ids = [int(row["item_id"]) for row in repo.list_items("PO-INV")]

    assert repo.get_returnable_map("PO-INV") == {item_ids[0]: 5.0, item_ids[1]: 3.0}

    repo.record_return(
        pid="PO-INV",
        date="2026-06-01",
        created_by=None,
        lines=[{"item_id": item_ids[0], "qty_return": 2.0}],
        notes="Return note",
    )

    rows = _purchase_rows(conn)
    return_rows = [row for row in rows if row["transaction_type"] == "purchase_return"]

    assert [(row["transaction_type"], row["txn_seq"]) for row in rows] == [
        ("purchase", 10),
        ("purchase", 20),
        ("purchase_return", 100),
    ]
    assert len(return_rows) == 1
    assert return_rows[0]["reference_item_id"] == item_ids[0]
    assert float(return_rows[0]["quantity"]) == pytest.approx(2.0)
    assert repo.get_returnable_map("PO-INV") == {item_ids[0]: 3.0, item_ids[1]: 3.0}

    events = AccountingService(conn).get_inventory_accounting_events(
        "purchases",
        "PO-INV",
    )
    assert [event.transaction_type for event in events] == [
        "purchase",
        "purchase",
        "purchase_return",
    ]

    filtered_events = AccountingService(conn).get_inventory_accounting_events(
        "purchases",
        "PO-INV",
        date_from="2026-06-01",
        date_to="2026-06-01",
        product_id=product_a,
    )
    assert [event.transaction_type for event in filtered_events] == [
        "purchase",
        "purchase_return",
    ]
