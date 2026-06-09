import sqlite3

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.repositories.purchases_repo import PurchasesRepo
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
    other_vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Other Payment Vendor', 'Test')"
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
        INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no)
        VALUES (?, 'Other Vendor Bank', 'Other Vendor Bank', '333')
        """,
        (other_vendor_id,),
    )
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-PAY', ?, '2026-06-09', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-PAY', ?, 1, ?, 100, 100, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 1, ?, 'purchase', 'purchases', 'PO-PAY', ?, '2026-06-09', 10)
        """,
        (product_id, uom_id, item_id),
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


def other_vendor_bank_id(conn):
    return int(
        conn.execute(
            "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE label = 'Other Vendor Bank'"
        ).fetchone()[0]
    )


def record_outgoing_bank_payment(
    repo,
    *,
    method,
    bank_account_id,
    vendor_bank_account_id=None,
    instrument_no="INST-1",
    temp_vendor_bank_name=None,
    temp_vendor_bank_number=None,
):
    instrument_types = {
        "Bank Transfer": "online",
        "Cheque": "cheque",
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
        instrument_no=instrument_no,
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


@pytest.mark.parametrize("clearing_state", ["posted", "pending", "bounced"])
def test_repository_rejects_uncleared_positive_vendor_payment(
    vendor_payment_db, clearing_state
):
    conn, repo, vendor_id = vendor_payment_db

    with pytest.raises(
        ValueError,
        match="Vendor purchase payments must have clearing_state='cleared'",
    ):
        record_cash_payment(repo, amount=125.0, clearing_state=clearing_state)

    assert conn.execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0
    assert VendorAdvancesRepo(conn).get_balance(vendor_id) == pytest.approx(0.0)


def test_repository_defaults_vendor_purchase_payment_to_cleared(vendor_payment_db):
    conn, repo, _vendor_id = vendor_payment_db

    payment_id = record_cash_payment(repo, amount=10.0, clearing_state=None)

    payment = conn.execute(
        "SELECT amount, clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert float(payment["amount"]) == pytest.approx(10.0)
    assert payment["clearing_state"] == "cleared"


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


def test_repository_rejects_negative_vendor_purchase_payment(vendor_payment_db):
    conn, repo, _vendor_id = vendor_payment_db

    with pytest.raises(
        ValueError,
        match="Vendor purchase payment amount must be greater than zero",
    ):
        record_cash_payment(repo, amount=-10.0, clearing_state="cleared")

    assert conn.execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0


def test_repository_rejects_card_vendor_purchase_payment(vendor_payment_db):
    conn, repo, _vendor_id = vendor_payment_db

    with pytest.raises(
        ValueError,
        match="Invalid vendor purchase payment method: Card",
    ):
        repo.record_payment(
            purchase_id="PO-PAY",
            amount=10.0,
            method="Card",
            bank_account_id=None,
            vendor_bank_account_id=None,
            instrument_type=None,
            instrument_no=None,
            instrument_date=None,
            deposited_date=None,
            cleared_date="2026-06-09",
            clearing_state="cleared",
            ref_no=None,
            notes=None,
            date="2026-06-09",
            created_by=None,
        )

    assert conn.execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0


def test_purchase_return_refund_creates_vendor_credit_not_negative_payment(
    vendor_payment_db,
):
    conn, _repo, vendor_id = vendor_payment_db
    item_id = conn.execute(
        "SELECT item_id FROM purchase_items WHERE purchase_id = 'PO-PAY'"
    ).fetchone()[0]

    PurchasesRepo(conn).record_return(
        pid="PO-PAY",
        date="2026-06-10",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 0.2}],
        notes="Returned goods refund",
        settlement={
            "mode": "refund_now",
            "method": "Cash",
            "clearing_state": "cleared",
            "notes": "Vendor refunded returned goods",
        },
    )

    assert conn.execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0
    credit = conn.execute(
        """
        SELECT amount, source_type, source_id, method, clearing_state, notes
        FROM vendor_advances
        WHERE vendor_id = ?
        """,
        (vendor_id,),
    ).fetchone()
    assert float(credit["amount"]) == pytest.approx(20.0)
    assert credit["source_type"] == "return_credit"
    assert credit["source_id"] == "PO-PAY"
    assert credit["method"] == "Cash"
    assert credit["clearing_state"] == "cleared"
    assert credit["notes"] == "Vendor refunded returned goods"


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
def test_repository_rejects_vendor_bank_account_from_different_purchase_vendor(
    vendor_payment_db, method
):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, _vendor_bank_id = payment_bank_ids(conn)

    with pytest.raises(
        ValueError,
        match="Vendor bank account does not belong to the purchase vendor",
    ):
        record_outgoing_bank_payment(
            repo,
            method=method,
            bank_account_id=company_bank_id,
            vendor_bank_account_id=other_vendor_bank_id(conn),
        )

    assert conn.execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0


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
def test_schema_rejects_wrong_vendor_bank_account_insert(vendor_payment_db, method):
    conn, _repo, _vendor_id = vendor_payment_db
    company_bank_id, _vendor_bank_id = payment_bank_ids(conn)
    bank_account_id = None if method == "Cash Deposit" else company_bank_id

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Vendor bank account must belong to the purchase vendor",
    ):
        conn.execute(
            """
            INSERT INTO purchase_payments (
                purchase_id, date, amount, method, bank_account_id,
                vendor_bank_account_id, instrument_type, instrument_no,
                instrument_date, cleared_date, clearing_state
            ) VALUES (
                'PO-PAY', '2026-06-09', 10, ?, ?, ?, ?, 'INST-1',
                '2026-06-09', '2026-06-09', 'cleared'
            )
            """,
            (
                method,
                bank_account_id,
                other_vendor_bank_id(conn),
                {
                    "Bank Transfer": "online",
                    "Cross Cheque": "cross_cheque",
                    "Cash Deposit": "cash_deposit",
                }[method],
            ),
        )


@pytest.mark.parametrize("method", ["Bank Transfer", "Cross Cheque", "Cash Deposit"])
def test_schema_rejects_wrong_vendor_bank_account_update(vendor_payment_db, method):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, vendor_bank_id = payment_bank_ids(conn)
    payment_id = record_outgoing_bank_payment(
        repo,
        method=method,
        bank_account_id=company_bank_id,
        vendor_bank_account_id=vendor_bank_id,
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Vendor bank account must belong to the purchase vendor",
    ):
        conn.execute(
            """
            UPDATE purchase_payments
               SET vendor_bank_account_id = ?
             WHERE payment_id = ?
            """,
            (other_vendor_bank_id(conn), payment_id),
        )

    payment = conn.execute(
        "SELECT vendor_bank_account_id FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert int(payment["vendor_bank_account_id"]) == vendor_bank_id


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


@pytest.mark.parametrize(
    "method", ["Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit"]
)
@pytest.mark.parametrize("instrument_no", ["", "   "])
def test_schema_rejects_blank_instrument_for_outgoing_bank_payment(
    vendor_payment_db, method, instrument_no
):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, vendor_bank_id = payment_bank_ids(conn)

    with pytest.raises(sqlite3.IntegrityError):
        record_outgoing_bank_payment(
            repo,
            method=method,
            bank_account_id=company_bank_id,
            vendor_bank_account_id=vendor_bank_id if method != "Cheque" else None,
            instrument_no=instrument_no,
        )


@pytest.mark.parametrize(
    "method", ["Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit"]
)
def test_schema_rejects_blank_instrument_on_payment_update(
    vendor_payment_db, method
):
    conn, repo, _vendor_id = vendor_payment_db
    company_bank_id, vendor_bank_id = payment_bank_ids(conn)
    payment_id = record_outgoing_bank_payment(
        repo,
        method=method,
        bank_account_id=company_bank_id,
        vendor_bank_account_id=vendor_bank_id if method != "Cheque" else None,
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE purchase_payments SET instrument_no = '   ' WHERE payment_id = ?",
            (payment_id,),
        )

    assert conn.execute(
        "SELECT instrument_no FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()[0] == "INST-1"


@pytest.mark.parametrize("clearing_state", ["posted", "pending", "bounced"])
def test_schema_rejects_uncleared_positive_vendor_payment_insert(
    vendor_payment_db, clearing_state
):
    conn, _repo, _vendor_id = vendor_payment_db

    with pytest.raises(
        sqlite3.IntegrityError,
        match="Vendor purchase payments must have clearing_state=cleared",
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
        match="Vendor purchase payments must have clearing_state=cleared",
    ):
        conn.execute(
            "UPDATE purchase_payments SET clearing_state = 'pending' WHERE payment_id = ?",
            (payment_id,),
        )

    assert conn.execute(
        "SELECT clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()[0] == "cleared"


def test_schema_rejects_negative_vendor_purchase_payment_insert(vendor_payment_db):
    conn, _repo, _vendor_id = vendor_payment_db

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO purchase_payments (
                purchase_id, date, amount, method, clearing_state
            ) VALUES ('PO-PAY', '2026-06-09', -10, 'Cash', 'cleared')
            """
        )


def test_schema_rejects_card_vendor_purchase_payment_insert(vendor_payment_db):
    conn, _repo, _vendor_id = vendor_payment_db

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO purchase_payments (
                purchase_id, date, amount, method, clearing_state
            ) VALUES ('PO-PAY', '2026-06-09', 10, 'Card', 'cleared')
            """
        )
