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
    conn.execute(
        "INSERT INTO company_info (company_id, company_name) VALUES (1, 'Payment Test Company')"
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Payment Vendor', 'Test')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO company_bank_accounts (label, bank_name, account_no)
        VALUES ('Payment Company Bank', 'Company Bank', '111')
        """
    )
    conn.execute(
        """
        INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no)
        VALUES (?, 'Payment Vendor Bank', 'Vendor Bank', '222')
        """,
        (vendor_id,),
    )
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


def payment_bank_ids(conn):
    company_bank_id = conn.execute(
        "SELECT account_id FROM company_bank_accounts WHERE label = 'Payment Company Bank'"
    ).fetchone()[0]
    vendor_bank_id = conn.execute(
        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE label = 'Payment Vendor Bank'"
    ).fetchone()[0]
    return int(company_bank_id), int(vendor_bank_id)


def record_outgoing_bank_payment(
    repo,
    *,
    method,
    bank_account_id,
    vendor_bank_account_id=None,
    temp_vendor_bank_name=None,
    temp_vendor_bank_number=None,
):
    instrument_types = {
        "Bank Transfer": "online",
        "Cross Cheque": "cross_cheque",
        "Cash Deposit": "cash_deposit",
    }
    return repo.record_payment(
        purchase_id="PO-PAY",
        amount=10.0,
        method=method,
        bank_account_id=bank_account_id if method != "Cash Deposit" else None,
        vendor_bank_account_id=vendor_bank_account_id,
        instrument_type=instrument_types[method],
        instrument_no="INST-1",
        instrument_date="2026-06-09",
        deposited_date=None,
        cleared_date="2026-06-09",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-09",
        created_by=None,
        temp_vendor_bank_name=temp_vendor_bank_name,
        temp_vendor_bank_number=temp_vendor_bank_number,
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


@pytest.mark.parametrize("method", ["Bank Transfer", "Cross Cheque", "Cash Deposit"])
def test_outgoing_bank_payment_accepts_complete_temporary_vendor_account(
    vendor_payment_db, method
):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, _vendor_bank_id = payment_bank_ids(conn)

    payment_id = record_outgoing_bank_payment(
        repo,
        method=method,
        bank_account_id=company_bank_id,
        temp_vendor_bank_name="Temporary Bank",
        temp_vendor_bank_number="TEMP-123",
    )

    payment = conn.execute(
        """
        SELECT vendor_bank_account_id, temp_vendor_bank_name, temp_vendor_bank_number
        FROM purchase_payments
        WHERE payment_id = ?
        """,
        (payment_id,),
    ).fetchone()
    assert payment["vendor_bank_account_id"] is None
    assert payment["temp_vendor_bank_name"] == "Temporary Bank"
    assert payment["temp_vendor_bank_number"] == "TEMP-123"


@pytest.mark.parametrize("method", ["Bank Transfer", "Cross Cheque", "Cash Deposit"])
def test_outgoing_bank_payment_still_accepts_saved_vendor_account(
    vendor_payment_db, method
):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, vendor_bank_id = payment_bank_ids(conn)

    payment_id = record_outgoing_bank_payment(
        repo,
        method=method,
        bank_account_id=company_bank_id,
        vendor_bank_account_id=vendor_bank_id,
    )

    payment = conn.execute(
        "SELECT vendor_bank_account_id FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert int(payment["vendor_bank_account_id"]) == vendor_bank_id


@pytest.mark.parametrize("method", ["Bank Transfer", "Cross Cheque", "Cash Deposit"])
def test_schema_update_accepts_complete_temporary_vendor_account(
    vendor_payment_db, method
):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, vendor_bank_id = payment_bank_ids(conn)
    payment_id = record_outgoing_bank_payment(
        repo,
        method=method,
        bank_account_id=company_bank_id,
        vendor_bank_account_id=vendor_bank_id,
    )

    conn.execute(
        """
        UPDATE purchase_payments
        SET vendor_bank_account_id = NULL,
            temp_vendor_bank_name = 'Updated Temporary Bank',
            temp_vendor_bank_number = 'UPDATED-123'
        WHERE payment_id = ?
        """,
        (payment_id,),
    )

    payment = conn.execute(
        """
        SELECT vendor_bank_account_id, temp_vendor_bank_name, temp_vendor_bank_number
        FROM purchase_payments
        WHERE payment_id = ?
        """,
        (payment_id,),
    ).fetchone()
    assert payment["vendor_bank_account_id"] is None
    assert payment["temp_vendor_bank_name"] == "Updated Temporary Bank"
    assert payment["temp_vendor_bank_number"] == "UPDATED-123"


@pytest.mark.parametrize("method", ["Bank Transfer", "Cross Cheque", "Cash Deposit"])
@pytest.mark.parametrize(
    ("temp_name", "temp_number"),
    [
        (None, "TEMP-123"),
        ("Temporary Bank", None),
        ("   ", "TEMP-123"),
        ("Temporary Bank", "   "),
    ],
)
def test_schema_rejects_incomplete_temporary_vendor_account_for_outgoing_bank_payment(
    vendor_payment_db, method, temp_name, temp_number
):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, _vendor_bank_id = payment_bank_ids(conn)

    with pytest.raises(
        sqlite3.IntegrityError,
        match="complete temporary account required for outgoing",
    ):
        record_outgoing_bank_payment(
            repo,
            method=method,
            bank_account_id=company_bank_id,
            temp_vendor_bank_name=temp_name,
            temp_vendor_bank_number=temp_number,
        )


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
