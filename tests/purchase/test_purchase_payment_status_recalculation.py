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
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL


@pytest.fixture()
def purchase_status_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Status Test Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Status Test Vendor', 'Test')"
    ).lastrowid

    purchases = PurchasesRepo(conn)
    header = PurchaseHeader(
        purchase_id="PO-STATUS",
        vendor_id=int(vendor_id),
        date="2026-06-10",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=None,
        created_by=None,
    )
    purchases.create_purchase(
        header,
        [
            PurchaseItem(
                None,
                header.purchase_id,
                int(product_id),
                1.0,
                int(uom_id),
                100.0,
                120.0,
                0.0,
            )
        ],
    )

    try:
        yield conn, purchases, PurchasePaymentsRepo(conn), VendorAdvancesRepo(conn), header
    finally:
        conn.close()


def _status(conn):
    return conn.execute(
        "SELECT payment_status FROM purchases WHERE purchase_id = 'PO-STATUS'"
    ).fetchone()["payment_status"]


def _record_payment(payments, amount):
    return payments.record_payment(
        purchase_id="PO-STATUS",
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-10",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-10",
        created_by=None,
    )


def test_purchase_edit_resets_paid_status_to_partial_or_unpaid(purchase_status_db):
    conn, purchases, payments, _advances, header = purchase_status_db
    payment_id = _record_payment(payments, 100.0)
    assert _status(conn) == "paid"

    item = purchases.list_items(header.purchase_id)[0]
    purchases.update_purchase(
        header,
        [
            PurchaseItem(
                int(item["item_id"]),
                header.purchase_id,
                int(item["product_id"]),
                2.0,
                int(item["uom_id"]),
                100.0,
                120.0,
                0.0,
            )
        ],
    )
    assert _status(conn) == "partial"

    conn.execute("DELETE FROM purchase_payments WHERE payment_id = ?", (payment_id,))
    assert _status(conn) == "unpaid"


def test_payment_and_credit_triggers_use_combined_settlement(purchase_status_db):
    conn, _purchases, payments, advances, header = purchase_status_db
    advances.grant_credit(
        vendor_id=header.vendor_id,
        amount=100.0,
        date="2026-06-10",
        notes=None,
        created_by=None,
    )
    application_id = advances.apply_credit_to_purchase(
        vendor_id=header.vendor_id,
        purchase_id=header.purchase_id,
        amount=40.0,
        date="2026-06-10",
        notes=None,
        created_by=None,
    )
    assert _status(conn) == "partial"

    payment_id = _record_payment(payments, 60.0)
    assert _status(conn) == "paid"

    conn.execute("DELETE FROM purchase_payments WHERE payment_id = ?", (payment_id,))
    assert _status(conn) == "partial"

    conn.execute("DELETE FROM vendor_advances WHERE tx_id = ?", (application_id,))
    assert _status(conn) == "unpaid"


def test_purchase_return_recalculates_status_against_net_total(purchase_status_db):
    conn, purchases, payments, _advances, header = purchase_status_db
    _record_payment(payments, 40.0)
    assert _status(conn) == "partial"

    item = purchases.list_items(header.purchase_id)[0]
    purchases.record_return(
        pid=header.purchase_id,
        date="2026-06-10",
        created_by=None,
        lines=[{"item_id": int(item["item_id"]), "qty_return": 0.6}],
        notes=None,
    )
    assert _status(conn) == "paid"
