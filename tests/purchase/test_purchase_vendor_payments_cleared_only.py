import sqlite3

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.purchase.controller import PurchaseController


@pytest.fixture()
def cleared_only_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Cleared Payment Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    conn.execute(
        "INSERT INTO company_info (company_id, company_name) VALUES (1, 'Cleared Payment Company')"
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Cleared Vendor', 'Test')"
    ).lastrowid
    company_bank_id = conn.execute(
        """
        INSERT INTO company_bank_accounts (label, bank_name, account_no)
        VALUES ('Cleared Company Bank', 'Company Bank', '111')
        """
    ).lastrowid
    vendor_bank_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no)
        VALUES (?, 'Cleared Vendor Bank', 'Vendor Bank', '222')
        """,
        (vendor_id,),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-CLEARED', ?, '2026-06-10', 300, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-CLEARED', ?, 3, ?, 100, 120, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 3, ?, 'purchase', 'purchases', 'PO-CLEARED', ?, '2026-06-10', 10)
        """,
        (product_id, uom_id, item_id),
    )

    try:
        yield {
            "conn": conn,
            "payments": PurchasePaymentsRepo(conn),
            "advances": VendorAdvancesRepo(conn),
            "vendor_id": int(vendor_id),
            "company_bank_id": int(company_bank_id),
            "vendor_bank_id": int(vendor_bank_id),
        }
    finally:
        conn.close()


def record_purchase_payment(db, *, method, clearing_state):
    instrument_types = {
        "Bank Transfer": "online",
        "Cheque": "cheque",
        "Cross Cheque": "cross_cheque",
    }
    needs_bank = method in {"Bank Transfer", "Cheque", "Cross Cheque"}
    needs_vendor_bank = method in {"Bank Transfer", "Cross Cheque"}
    return db["payments"].record_payment(
        purchase_id="PO-CLEARED",
        amount=10.0,
        method=method,
        bank_account_id=db["company_bank_id"] if needs_bank else None,
        vendor_bank_account_id=db["vendor_bank_id"] if needs_vendor_bank else None,
        instrument_type=instrument_types.get(method),
        instrument_no="INST-1" if needs_bank else None,
        instrument_date="2026-06-10" if needs_bank else None,
        deposited_date=None,
        cleared_date="2026-06-10" if clearing_state == "cleared" else None,
        clearing_state=clearing_state,
        ref_no=None,
        notes=None,
        date="2026-06-10",
        created_by=None,
    )


@pytest.mark.parametrize("clearing_state", ["pending", "bounced"])
def test_purchase_payment_repository_rejects_non_cleared_states(
    cleared_only_db, clearing_state
):
    with pytest.raises(
        ValueError,
        match="Vendor purchase payments must have clearing_state='cleared'",
    ):
        record_purchase_payment(cleared_only_db, method="Cash", clearing_state=clearing_state)

    assert (
        cleared_only_db["conn"]
        .execute("SELECT COUNT(*) FROM purchase_payments")
        .fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("clearing_state", ["pending", "bounced"])
def test_purchase_payment_schema_rejects_non_cleared_states(
    cleared_only_db, clearing_state
):
    with pytest.raises(sqlite3.IntegrityError, match="clearing_state=cleared"):
        cleared_only_db["conn"].execute(
            """
            INSERT INTO purchase_payments (
                purchase_id, date, amount, method, clearing_state
            ) VALUES ('PO-CLEARED', '2026-06-10', 10, 'Cash', ?)
            """,
            (clearing_state,),
        )

    assert (
        cleared_only_db["conn"]
        .execute("SELECT COUNT(*) FROM purchase_payments")
        .fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("method", ["Cheque", "Cross Cheque", "Bank Transfer"])
def test_vendor_outgoing_instrument_methods_are_recorded_as_cleared(
    cleared_only_db, method
):
    payment_id = record_purchase_payment(
        cleared_only_db, method=method, clearing_state="cleared"
    )

    row = cleared_only_db["conn"].execute(
        "SELECT method, clearing_state FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()
    assert row["method"] == method
    assert row["clearing_state"] == "cleared"


def test_purchase_controller_exposes_no_pending_or_bounced_payment_actions():
    assert not hasattr(PurchaseController, "mark_payment_cleared")
    assert not hasattr(PurchaseController, "mark_payment_bounced")


def test_purchase_payments_repo_exposes_no_pending_instrument_helper():
    assert not hasattr(PurchasePaymentsRepo, "list_pending_instruments")


@pytest.mark.parametrize("clearing_state", ["pending", "bounced"])
def test_vendor_advance_repository_rejects_non_cleared_outgoing_payment_metadata(
    cleared_only_db, clearing_state
):
    with pytest.raises(
        ValueError,
        match="Vendor outgoing payments must have clearing_state='cleared'",
    ):
        cleared_only_db["advances"].grant_credit(
            vendor_id=cleared_only_db["vendor_id"],
            amount=50.0,
            date="2026-06-10",
            notes=None,
            created_by=None,
            source_type="deposit",
            clearing_state=clearing_state,
        )

    assert cleared_only_db["advances"].get_balance(cleared_only_db["vendor_id"]) == 0.0


def test_vendor_advance_repository_accepts_cleared_outgoing_payment_metadata(
    cleared_only_db,
):
    tx_id = cleared_only_db["advances"].grant_credit(
        vendor_id=cleared_only_db["vendor_id"],
        amount=50.0,
        date="2026-06-10",
        notes=None,
        created_by=None,
        source_type="deposit",
        clearing_state="cleared",
    )

    row = cleared_only_db["conn"].execute(
        "SELECT amount, clearing_state FROM vendor_advances WHERE tx_id = ?",
        (tx_id,),
    ).fetchone()
    assert float(row["amount"]) == pytest.approx(50.0)
    assert row["clearing_state"] == "cleared"
    assert cleared_only_db["advances"].get_balance(
        cleared_only_db["vendor_id"]
    ) == pytest.approx(50.0)


@pytest.mark.parametrize("clearing_state", ["pending", "bounced"])
def test_vendor_advance_schema_rejects_non_cleared_direct_insert(
    cleared_only_db, clearing_state
):
    with pytest.raises(sqlite3.IntegrityError, match="clearing_state=cleared"):
        cleared_only_db["conn"].execute(
            """
            INSERT INTO vendor_advances (
                vendor_id, tx_date, amount, source_type, clearing_state
            ) VALUES (?, '2026-06-10', 50, 'deposit', ?)
            """,
            (cleared_only_db["vendor_id"], clearing_state),
        )

    assert cleared_only_db["advances"].get_balance(cleared_only_db["vendor_id"]) == 0.0


def test_vendor_advance_schema_accepts_cleared_direct_insert(cleared_only_db):
    tx_id = cleared_only_db["conn"].execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, clearing_state
        ) VALUES (?, '2026-06-10', 50, 'deposit', 'cleared')
        """,
        (cleared_only_db["vendor_id"],),
    ).lastrowid

    row = cleared_only_db["conn"].execute(
        "SELECT amount, clearing_state FROM vendor_advances WHERE tx_id = ?",
        (tx_id,),
    ).fetchone()
    assert float(row["amount"]) == pytest.approx(50.0)
    assert row["clearing_state"] == "cleared"


def test_vendor_advance_schema_accepts_null_clearing_state_for_credit_entries(
    cleared_only_db,
):
    tx_id = cleared_only_db["conn"].execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type
        ) VALUES (?, '2026-06-10', 50, 'deposit')
        """,
        (cleared_only_db["vendor_id"],),
    ).lastrowid

    row = cleared_only_db["conn"].execute(
        "SELECT amount, clearing_state FROM vendor_advances WHERE tx_id = ?",
        (tx_id,),
    ).fetchone()
    assert float(row["amount"]) == pytest.approx(50.0)
    assert row["clearing_state"] is None


@pytest.mark.parametrize("clearing_state", ["pending", "bounced"])
def test_vendor_advance_schema_rejects_non_cleared_direct_update(
    cleared_only_db, clearing_state
):
    tx_id = cleared_only_db["conn"].execute(
        """
        INSERT INTO vendor_advances (
            vendor_id, tx_date, amount, source_type, clearing_state
        ) VALUES (?, '2026-06-10', 50, 'deposit', 'cleared')
        """,
        (cleared_only_db["vendor_id"],),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="clearing_state=cleared"):
        cleared_only_db["conn"].execute(
            "UPDATE vendor_advances SET clearing_state = ? WHERE tx_id = ?",
            (clearing_state, tx_id),
        )

    row = cleared_only_db["conn"].execute(
        "SELECT clearing_state FROM vendor_advances WHERE tx_id = ?",
        (tx_id,),
    ).fetchone()
    assert row["clearing_state"] == "cleared"
