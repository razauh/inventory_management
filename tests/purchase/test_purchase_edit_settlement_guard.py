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
def purchase_edit_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Edit Settlement Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Edit Settlement Vendor', 'Test')"
    ).lastrowid

    try:
        yield {
            "conn": conn,
            "repo": PurchasesRepo(conn),
            "payments": PurchasePaymentsRepo(conn),
            "advances": VendorAdvancesRepo(conn),
            "vendor_id": int(vendor_id),
            "product_id": int(product_id),
            "uom_id": int(uom_id),
        }
    finally:
        conn.close()


def _header(db, purchase_id):
    return PurchaseHeader(
        purchase_id=purchase_id,
        vendor_id=db["vendor_id"],
        date="2026-06-10",
        total_amount=0.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=None,
        created_by=None,
    )


def _create_purchase(db, purchase_id, *, quantity=1.0, price=100.0):
    header = _header(db, purchase_id)
    db["repo"].create_purchase(
        header,
        [
            PurchaseItem(
                None,
                purchase_id,
                db["product_id"],
                quantity,
                db["uom_id"],
                price,
                price,
                0.0,
            )
        ],
    )
    item = db["repo"].list_items(purchase_id)[0]
    return header, int(item["item_id"])


def _edit_single_line(db, header, item_id, *, quantity=1.0, price=100.0):
    db["repo"].update_purchase(
        header,
        [
            PurchaseItem(
                item_id,
                header.purchase_id,
                db["product_id"],
                quantity,
                db["uom_id"],
                price,
                price,
                0.0,
            )
        ],
    )


def _record_payment(db, purchase_id, amount):
    db["payments"].record_payment(
        purchase_id=purchase_id,
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


def _purchase_total(conn, purchase_id):
    row = conn.execute(
        """
        SELECT CAST(total_amount AS REAL) AS total_amount
        FROM purchases
        WHERE purchase_id = ?
        """,
        (purchase_id,),
    ).fetchone()
    return float(row["total_amount"])


def test_edit_rejects_reduction_below_cleared_purchase_payments(purchase_edit_db):
    db = purchase_edit_db
    header, item_id = _create_purchase(db, "PO-EDIT-PAID")
    _record_payment(db, header.purchase_id, 80.0)

    with pytest.raises(ValueError, match="below settled amount"):
        _edit_single_line(db, header, item_id, price=70.0)

    assert _purchase_total(db["conn"], header.purchase_id) == pytest.approx(100.0)


def test_edit_rejects_reduction_below_applied_vendor_credit(purchase_edit_db):
    db = purchase_edit_db
    header, item_id = _create_purchase(db, "PO-EDIT-CREDIT")
    db["advances"].grant_credit(
        vendor_id=db["vendor_id"],
        amount=40.0,
        date="2026-06-10",
        notes=None,
        created_by=None,
    )
    db["advances"].apply_credit_to_purchase(
        vendor_id=db["vendor_id"],
        purchase_id=header.purchase_id,
        amount=40.0,
        date="2026-06-10",
        notes=None,
        created_by=None,
    )

    with pytest.raises(ValueError, match="below settled amount"):
        _edit_single_line(db, header, item_id, price=30.0)

    assert _purchase_total(db["conn"], header.purchase_id) == pytest.approx(100.0)


def test_edit_compares_settlement_to_net_total_after_returns(purchase_edit_db):
    db = purchase_edit_db
    header, item_id = _create_purchase(db, "PO-EDIT-RETURN", quantity=12.0, price=10.0)
    _record_payment(db, header.purchase_id, 90.0)
    db["repo"].record_return(
        pid=header.purchase_id,
        date="2026-06-11",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 2.0}],
        notes=None,
    )

    _edit_single_line(db, header, item_id, quantity=11.5, price=10.0)
    assert _purchase_total(db["conn"], header.purchase_id) == pytest.approx(115.0)

    with pytest.raises(ValueError, match="below settled amount"):
        _edit_single_line(db, header, item_id, quantity=10.5, price=10.0)

    assert _purchase_total(db["conn"], header.purchase_id) == pytest.approx(115.0)
