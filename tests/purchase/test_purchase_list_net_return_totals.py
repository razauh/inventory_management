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
from inventory_management.modules.purchase.model import PurchasesTableModel


@pytest.fixture()
def purchase_list_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Purchase List Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Purchase List Vendor', 'Test')"
    ).lastrowid

    try:
        yield conn, {
            "uom_id": int(uom_id),
            "product_id": int(product_id),
            "vendor_id": int(vendor_id),
        }
    finally:
        conn.close()


def _create_purchase(conn, ids):
    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id="PO-LIST-NET",
            vendor_id=ids["vendor_id"],
            date="2026-06-10",
            total_amount=0.0,
            order_discount=0.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=None,
        ),
        [
            PurchaseItem(
                None,
                "PO-LIST-NET",
                ids["product_id"],
                1.0,
                ids["uom_id"],
                100.0,
                150.0,
                0.0,
            )
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
        cleared_date="2026-06-10",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-10",
        created_by=None,
    )


def test_list_purchases_returns_gross_returned_net_and_due_on_same_basis(
    purchase_list_db,
):
    conn, ids = purchase_list_db
    repo = _create_purchase(conn, ids)
    _record_cash_payment(conn, "PO-LIST-NET", 40.0)

    item = repo.list_items("PO-LIST-NET")[0]
    repo.record_return(
        pid="PO-LIST-NET",
        date="2026-06-10",
        created_by=None,
        lines=[{"item_id": int(item["item_id"]), "qty_return": 0.6}],
        notes=None,
    )

    row = dict(repo.list_purchases()[0])

    assert row["payment_status"] == "paid"
    assert row["total_amount"] == pytest.approx(100.0)
    assert row["returned_value"] == pytest.approx(60.0)
    assert row["calculated_total_amount"] == pytest.approx(40.0)
    assert row["paid_amount"] == pytest.approx(40.0)
    assert row["remaining_due"] == pytest.approx(0.0)


def test_purchase_table_model_displays_net_and_due_columns(purchase_list_db):
    conn, ids = purchase_list_db
    repo = _create_purchase(conn, ids)
    _record_cash_payment(conn, "PO-LIST-NET", 40.0)

    item = repo.list_items("PO-LIST-NET")[0]
    repo.record_return(
        pid="PO-LIST-NET",
        date="2026-06-10",
        created_by=None,
        lines=[{"item_id": int(item["item_id"]), "qty_return": 0.6}],
        notes=None,
    )

    model = PurchasesTableModel([dict(repo.list_purchases()[0])])
    displayed = [
        model.data(model.index(0, column))
        for column in range(model.columnCount())
    ]

    assert displayed[3] == "100.00"
    assert displayed[4] == "60.00"
    assert displayed[5] == "40.00"
    assert displayed[6] == "40.00"
    assert displayed[7] == "0.00"
    assert displayed[8] == "paid"
