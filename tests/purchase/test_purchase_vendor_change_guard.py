import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from inventory_management.database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.repositories.vendor_advances_repo import VendorAdvancesRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.purchase.controller import PurchaseController


PURCHASE_ID = "PO-VENDOR-GUARD"


@pytest.fixture()
def purchase_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_a = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor A', 'A')"
    ).lastrowid
    vendor_b = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor B', 'B')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Vendor Guard Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    repo = PurchasesRepo(conn)
    header = PurchaseHeader(
        purchase_id=PURCHASE_ID,
        vendor_id=int(vendor_a),
        date="2026-06-01",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=None,
        created_by=None,
    )
    repo.create_purchase(
        header,
        [
            PurchaseItem(
                None,
                PURCHASE_ID,
                int(product_id),
                10.0,
                int(uom_id),
                10.0,
                12.0,
                0.0,
            )
        ],
    )

    try:
        yield {
            "conn": conn,
            "repo": repo,
            "vendor_a": int(vendor_a),
            "vendor_b": int(vendor_b),
            "item": repo.list_items(PURCHASE_ID)[0],
        }
    finally:
        conn.close()


def _changed_header(db):
    return PurchaseHeader(
        purchase_id=PURCHASE_ID,
        vendor_id=db["vendor_b"],
        date="2026-06-01",
        total_amount=100.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=None,
        created_by=None,
    )


def _items(db):
    item = db["item"]
    return [
        PurchaseItem(
            int(item["item_id"]),
            PURCHASE_ID,
            int(item["product_id"]),
            float(item["quantity"]),
            int(item["uom_id"]),
            float(item["purchase_price"]),
            float(item["sale_price"]),
            float(item["item_discount"]),
        )
    ]


def _add_payment(db):
    PurchasePaymentsRepo(db["conn"]).record_payment(
        PURCHASE_ID,
        amount=20.0,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-02",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-02",
        created_by=None,
    )


def _add_applied_credit(db):
    advances = VendorAdvancesRepo(db["conn"])
    advances.grant_credit(
        db["vendor_a"],
        20.0,
        date="2026-06-02",
        notes="Credit",
        created_by=None,
    )
    advances.apply_credit_to_purchase(
        db["vendor_a"],
        PURCHASE_ID,
        20.0,
        date="2026-06-02",
        notes="Applied",
        created_by=None,
    )


def _add_return(db):
    db["repo"].record_return(
        pid=PURCHASE_ID,
        date="2026-06-02",
        created_by=None,
        lines=[{"item_id": int(db["item"]["item_id"]), "qty_return": 1.0}],
        notes="Return",
    )


@pytest.mark.parametrize("add_activity", [_add_payment, _add_applied_credit, _add_return])
def test_repository_rejects_vendor_change_after_financial_or_return_activity(
    purchase_db, add_activity
):
    add_activity(purchase_db)

    with pytest.raises(ValueError, match="Cannot change the purchase vendor"):
        purchase_db["repo"].update_purchase(
            _changed_header(purchase_db), _items(purchase_db)
        )

    assert purchase_db["repo"].get_header(PURCHASE_ID)["vendor_id"] == purchase_db["vendor_a"]


def test_repository_allows_vendor_change_before_activity_exists(purchase_db):
    purchase_db["repo"].update_purchase(
        _changed_header(purchase_db), _items(purchase_db)
    )

    assert purchase_db["repo"].get_header(PURCHASE_ID)["vendor_id"] == purchase_db["vendor_b"]


def test_repository_allows_same_vendor_edit_after_activity(purchase_db):
    _add_payment(purchase_db)
    header = _changed_header(purchase_db)
    header.vendor_id = purchase_db["vendor_a"]

    purchase_db["repo"].update_purchase(header, _items(purchase_db))

    assert purchase_db["repo"].get_header(PURCHASE_ID)["vendor_id"] == purchase_db["vendor_a"]


@pytest.mark.parametrize("add_activity", [_add_payment, _add_applied_credit, _add_return])
def test_schema_blocks_direct_vendor_change_after_activity(purchase_db, add_activity):
    add_activity(purchase_db)

    with pytest.raises(sqlite3.IntegrityError, match="Cannot change the purchase vendor"):
        purchase_db["conn"].execute(
            "UPDATE purchases SET vendor_id=? WHERE purchase_id=?",
            (purchase_db["vendor_b"], PURCHASE_ID),
        )

    assert purchase_db["repo"].get_header(PURCHASE_ID)["vendor_id"] == purchase_db["vendor_a"]


def test_edit_disables_vendor_selector_when_purchase_is_locked(purchase_db):
    _add_payment(purchase_db)
    controller = PurchaseController.__new__(PurchaseController)
    controller.repo = purchase_db["repo"]
    controller.view = None
    controller.vendors = MagicMock()
    controller.products = MagicMock()
    controller._selected_row_dict = MagicMock(
        return_value={
            "purchase_id": PURCHASE_ID,
            "vendor_id": purchase_db["vendor_a"],
            "date": "2026-06-01",
            "order_discount": 0.0,
            "payment_status": "partial",
            "paid_amount": 20.0,
            "advance_payment_applied": 0.0,
            "notes": None,
        }
    )

    with patch("inventory_management.modules.purchase.controller.PurchaseForm") as form_cls:
        dialog = form_cls.return_value
        dialog.exec.return_value = False
        controller._edit()

    dialog.cmb_vendor.setEnabled.assert_called_once_with(False)
    assert "cannot be changed" in dialog.cmb_vendor.setToolTip.call_args.args[0].lower()
