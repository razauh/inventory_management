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
def negative_due_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Negative Due Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Negative Due Vendor', 'Test')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status
        ) VALUES ('PO-NEG-DUE', ?, '2026-06-10', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-NEG-DUE', ?, 1, ?, 80, 80, 0)
        """,
        (product_id, uom_id),
    )
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, clearing_state, cleared_date
        ) VALUES ('PO-NEG-DUE', '2026-06-10', 100, 'Cash', 'cleared', '2026-06-10')
        """
    )

    try:
        yield conn, PurchasePaymentsRepo(conn), int(vendor_id)
    finally:
        conn.close()


def _record_cash_payment(repo, amount):
    return repo.record_payment(
        purchase_id="PO-NEG-DUE",
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


def test_negative_existing_due_does_not_inflate_new_vendor_credit(negative_due_db):
    conn, repo, vendor_id = negative_due_db

    credit_tx_id = _record_cash_payment(repo, 100.0)

    credit = conn.execute(
        "SELECT amount, source_type FROM vendor_advances WHERE tx_id = ?",
        (credit_tx_id,),
    ).fetchone()
    assert float(credit["amount"]) == pytest.approx(100.0)
    assert credit["source_type"] == "deposit"
    assert VendorAdvancesRepo(conn).get_balance(vendor_id) == pytest.approx(100.0)
    assert conn.execute(
        "SELECT COUNT(*) FROM purchase_payments WHERE purchase_id = 'PO-NEG-DUE'"
    ).fetchone()[0] == 1


def test_positive_due_still_converts_only_new_payment_excess(negative_due_db):
    conn, repo, vendor_id = negative_due_db
    conn.execute(
        "DELETE FROM purchase_payments WHERE purchase_id = 'PO-NEG-DUE'"
    )

    payment_id = _record_cash_payment(repo, 100.0)

    payment = conn.execute(
        "SELECT amount FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert float(payment["amount"]) == pytest.approx(80.0)
    assert VendorAdvancesRepo(conn).get_balance(vendor_id) == pytest.approx(20.0)
