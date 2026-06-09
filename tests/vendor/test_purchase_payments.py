import sqlite3

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL


@pytest.fixture()
def vendor_payment_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Payment Test Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Payment Vendor', 'Test')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-PAY', ?, '2026-06-09', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-PAY', ?, 1, ?, 100, 100, 0)
        """,
        (product_id, uom_id),
    )

    try:
        yield conn, PurchasePaymentsRepo(conn), int(vendor_id)
    finally:
        conn.close()


def record_cash_payment(repo, *, amount, clearing_state):
    return repo.record_payment(
        purchase_id="PO-PAY",
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-09" if clearing_state == "cleared" else None,
        clearing_state=clearing_state,
        ref_no=None,
        notes=None,
        date="2026-06-09",
        created_by=None,
    )


@pytest.mark.parametrize("clearing_state", [None, "posted", "pending", "bounced"])
def test_repository_rejects_uncleared_positive_vendor_payment(
    vendor_payment_db, clearing_state
):
    conn, repo, vendor_id = vendor_payment_db

    with pytest.raises(
        ValueError,
        match="Positive vendor payments must have clearing_state='cleared'",
    ):
        record_cash_payment(repo, amount=125.0, clearing_state=clearing_state)

    assert conn.execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0
    assert VendorAdvancesRepo(conn).get_balance(vendor_id) == pytest.approx(0.0)


def test_cleared_overpayment_creates_only_excess_vendor_credit(vendor_payment_db):
    conn, repo, vendor_id = vendor_payment_db

    payment_id = record_cash_payment(repo, amount=125.0, clearing_state="cleared")

    payment = conn.execute(
        "SELECT amount, clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert float(payment["amount"]) == pytest.approx(100.0)
    assert payment["clearing_state"] == "cleared"
    assert VendorAdvancesRepo(conn).get_balance(vendor_id) == pytest.approx(25.0)
    assert conn.execute(
        "SELECT paid_amount FROM purchases WHERE purchase_id = 'PO-PAY'"
    ).fetchone()[0] == pytest.approx(100.0)


def test_negative_vendor_refund_can_remain_pending(vendor_payment_db):
    conn, repo, _vendor_id = vendor_payment_db

    payment_id = record_cash_payment(repo, amount=-10.0, clearing_state="pending")

    payment = conn.execute(
        "SELECT amount, clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert float(payment["amount"]) == pytest.approx(-10.0)
    assert payment["clearing_state"] == "pending"


@pytest.mark.parametrize("clearing_state", ["posted", "pending", "bounced"])
def test_schema_rejects_uncleared_positive_vendor_payment_insert(
    vendor_payment_db, clearing_state
):
    conn, _repo, _vendor_id = vendor_payment_db

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Positive vendor payments must have clearing_state=cleared",
    ):
        conn.execute(
            """
            INSERT INTO purchase_payments (
                purchase_id, date, amount, method, clearing_state
            ) VALUES ('PO-PAY', '2026-06-09', 10, 'Cash', ?)
            """,
            (clearing_state,),
        )


def test_schema_rejects_changing_positive_vendor_payment_from_cleared(
    vendor_payment_db,
):
    conn, repo, _vendor_id = vendor_payment_db
    payment_id = record_cash_payment(repo, amount=10.0, clearing_state="cleared")

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Positive vendor payments must have clearing_state=cleared",
    ):
        conn.execute(
            "UPDATE purchase_payments SET clearing_state = 'pending' WHERE payment_id = ?",
            (payment_id,),
        )

    assert conn.execute(
        "SELECT clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()[0] == "cleared"
