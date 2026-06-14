import sqlite3

import pytest

from inventory_management.database.repositories.vendor_advances_repo import (
    OverapplyVendorAdvanceError,
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL


@pytest.fixture()
def returned_purchase_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Returned Credit Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Returned Credit Vendor', 'Test')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-NET-DUE', ?, '2026-06-10', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-NET-DUE', ?, 10, ?, 10, 12, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (
            ?, 10, ?, 'purchase', 'purchases',
            'PO-NET-DUE', ?, '2026-06-10', 10
        )
        """,
        (product_id, uom_id, item_id),
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (
            ?, 4, ?, 'purchase_return', 'purchases',
            'PO-NET-DUE', ?, '2026-06-11', 20
        )
        """,
        (product_id, uom_id, item_id),
    )

    try:
        yield conn, VendorAdvancesRepo(conn), int(vendor_id)
    finally:
        conn.close()


def _grant_credit(repo, vendor_id, amount):
    repo.grant_credit(
        vendor_id=vendor_id,
        amount=amount,
        date="2026-06-10",
        notes=None,
        created_by=None,
    )


def test_vendor_credit_prevalidation_uses_net_due_after_returns(returned_purchase_db):
    conn, repo, vendor_id = returned_purchase_db
    _grant_credit(repo, vendor_id, 100.0)

    net_total = conn.execute(
        """
        SELECT calculated_total_amount
        FROM purchase_detailed_totals
        WHERE purchase_id = 'PO-NET-DUE'
        """
    ).fetchone()[0]
    assert float(net_total) == pytest.approx(60.0)

    with pytest.raises(
        OverapplyVendorAdvanceError,
        match=r"Cannot apply 70\.00 beyond remaining due 60\.00",
    ):
        repo.apply_credit_to_purchase(
            vendor_id=vendor_id,
            purchase_id="PO-NET-DUE",
            amount=70.0,
            date="2026-06-11",
            notes=None,
            created_by=None,
        )

    assert conn.execute(
        """
        SELECT COUNT(*)
        FROM vendor_advances
        WHERE source_type = 'applied_to_purchase'
          AND source_id = 'PO-NET-DUE'
        """
    ).fetchone()[0] == 0
    assert repo.get_balance(vendor_id) == pytest.approx(100.0)


def test_vendor_credit_can_apply_exact_net_due_after_returns(returned_purchase_db):
    conn, repo, vendor_id = returned_purchase_db
    _grant_credit(repo, vendor_id, 100.0)

    repo.apply_credit_to_purchase(
        vendor_id=vendor_id,
        purchase_id="PO-NET-DUE",
        amount=60.0,
        date="2026-06-11",
        notes=None,
        created_by=None,
    )

    assert conn.execute(
        "SELECT advance_payment_applied FROM purchases WHERE purchase_id = 'PO-NET-DUE'"
    ).fetchone()[0] == pytest.approx(60.0)
    assert repo.get_balance(vendor_id) == pytest.approx(40.0)
