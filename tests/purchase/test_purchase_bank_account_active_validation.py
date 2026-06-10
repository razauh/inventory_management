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
def purchase_bank_validation_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Bank Validation Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    conn.execute(
        "INSERT INTO company_info (company_id, company_name) VALUES (1, 'Bank Validation Company')"
    )
    active_company_account_id = conn.execute(
        """
        INSERT INTO company_bank_accounts (label, bank_name, account_no, is_active)
        VALUES ('Active Company Bank', 'Company Bank', '111', 1)
        """
    ).lastrowid
    inactive_company_account_id = conn.execute(
        """
        INSERT INTO company_bank_accounts (label, bank_name, account_no, is_active)
        VALUES ('Inactive Company Bank', 'Company Bank', '222', 0)
        """
    ).lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Bank Validation Vendor', 'Test')"
    ).lastrowid
    other_vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Other Bank Vendor', 'Test')"
    ).lastrowid
    active_vendor_account_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_active
        ) VALUES (?, 'Active Vendor Bank', 'Vendor Bank', '333', 1)
        """,
        (vendor_id,),
    ).lastrowid
    inactive_vendor_account_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_active
        ) VALUES (?, 'Inactive Vendor Bank', 'Vendor Bank', '444', 0)
        """,
        (vendor_id,),
    ).lastrowid
    other_vendor_account_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (
            vendor_id, label, bank_name, account_no, is_active
        ) VALUES (?, 'Other Vendor Bank', 'Other Vendor Bank', '555', 1)
        """,
        (other_vendor_id,),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, payment_status)
        VALUES ('PO-BANK-ACTIVE', ?, '2026-06-09', 100, 'unpaid')
        """,
        (vendor_id,),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES ('PO-BANK-ACTIVE', ?, 1, ?, 100, 120, 0)
        """,
        (product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 1, ?, 'purchase', 'purchases', 'PO-BANK-ACTIVE', ?, '2026-06-09', 10)
        """,
        (product_id, uom_id, item_id),
    )

    try:
        yield {
            "conn": conn,
            "payments": PurchasePaymentsRepo(conn),
            "advances": VendorAdvancesRepo(conn),
            "vendor_id": int(vendor_id),
            "active_company_account_id": int(active_company_account_id),
            "inactive_company_account_id": int(inactive_company_account_id),
            "active_vendor_account_id": int(active_vendor_account_id),
            "inactive_vendor_account_id": int(inactive_vendor_account_id),
            "other_vendor_account_id": int(other_vendor_account_id),
        }
    finally:
        conn.close()


def record_bank_transfer_payment(ctx, *, company_account_id, vendor_account_id):
    return ctx["payments"].record_payment(
        purchase_id="PO-BANK-ACTIVE",
        amount=10.0,
        method="Bank Transfer",
        bank_account_id=company_account_id,
        vendor_bank_account_id=vendor_account_id,
        instrument_type="online",
        instrument_no="TXN-1",
        instrument_date="2026-06-09",
        deposited_date=None,
        cleared_date="2026-06-09",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-09",
        created_by=None,
    )


def grant_vendor_deposit(ctx, *, company_account_id, vendor_account_id):
    return ctx["advances"].grant_credit(
        vendor_id=ctx["vendor_id"],
        amount=10.0,
        date="2026-06-09",
        notes=None,
        created_by=None,
        source_type="deposit",
        method="Bank Transfer",
        bank_account_id=company_account_id,
        vendor_bank_account_id=vendor_account_id,
        instrument_type="online",
        instrument_no="TXN-1",
        clearing_state="cleared",
    )


def test_purchase_payment_accepts_active_bank_accounts(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    payment_id = record_bank_transfer_payment(
        ctx,
        company_account_id=ctx["active_company_account_id"],
        vendor_account_id=ctx["active_vendor_account_id"],
    )

    assert ctx["conn"].execute(
        "SELECT COUNT(*) FROM purchase_payments WHERE payment_id = ?",
        (payment_id,),
    ).fetchone()[0] == 1


def test_purchase_payment_rejects_inactive_company_account(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    with pytest.raises(ValueError, match="company bank account is inactive"):
        record_bank_transfer_payment(
            ctx,
            company_account_id=ctx["inactive_company_account_id"],
            vendor_account_id=ctx["active_vendor_account_id"],
        )

    assert ctx["conn"].execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0


def test_purchase_payment_rejects_inactive_vendor_account(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    with pytest.raises(ValueError, match="vendor bank account is inactive"):
        record_bank_transfer_payment(
            ctx,
            company_account_id=ctx["active_company_account_id"],
            vendor_account_id=ctx["inactive_vendor_account_id"],
        )

    assert ctx["conn"].execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0


def test_purchase_payment_rejects_other_vendor_account(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    with pytest.raises(ValueError, match="does not belong to the purchase vendor"):
        record_bank_transfer_payment(
            ctx,
            company_account_id=ctx["active_company_account_id"],
            vendor_account_id=ctx["other_vendor_account_id"],
        )

    assert ctx["conn"].execute("SELECT COUNT(*) FROM purchase_payments").fetchone()[0] == 0


def test_vendor_advance_accepts_active_bank_accounts(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    tx_id = grant_vendor_deposit(
        ctx,
        company_account_id=ctx["active_company_account_id"],
        vendor_account_id=ctx["active_vendor_account_id"],
    )

    assert ctx["conn"].execute(
        "SELECT COUNT(*) FROM vendor_advances WHERE tx_id = ?",
        (tx_id,),
    ).fetchone()[0] == 1


def test_vendor_advance_rejects_inactive_company_account(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    with pytest.raises(ValueError, match="company bank account is inactive"):
        grant_vendor_deposit(
            ctx,
            company_account_id=ctx["inactive_company_account_id"],
            vendor_account_id=ctx["active_vendor_account_id"],
        )

    assert ctx["conn"].execute("SELECT COUNT(*) FROM vendor_advances").fetchone()[0] == 0


def test_vendor_advance_rejects_inactive_vendor_account(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    with pytest.raises(ValueError, match="vendor bank account is inactive"):
        grant_vendor_deposit(
            ctx,
            company_account_id=ctx["active_company_account_id"],
            vendor_account_id=ctx["inactive_vendor_account_id"],
        )

    assert ctx["conn"].execute("SELECT COUNT(*) FROM vendor_advances").fetchone()[0] == 0


def test_vendor_advance_rejects_other_vendor_account(purchase_bank_validation_db):
    ctx = purchase_bank_validation_db

    with pytest.raises(ValueError, match="does not belong to the advance vendor"):
        grant_vendor_deposit(
            ctx,
            company_account_id=ctx["active_company_account_id"],
            vendor_account_id=ctx["other_vendor_account_id"],
        )

    assert ctx["conn"].execute("SELECT COUNT(*) FROM vendor_advances").fetchone()[0] == 0


def test_schema_rejects_direct_purchase_payment_with_inactive_company_account(
    purchase_bank_validation_db,
):
    ctx = purchase_bank_validation_db

    with pytest.raises(sqlite3.IntegrityError, match="company bank account is inactive"):
        ctx["conn"].execute(
            """
            INSERT INTO purchase_payments (
                purchase_id, date, amount, method, bank_account_id,
                vendor_bank_account_id, instrument_type, instrument_no,
                cleared_date, clearing_state
            ) VALUES (
                'PO-BANK-ACTIVE', '2026-06-09', 10, 'Bank Transfer', ?,
                ?, 'online', 'TXN-1', '2026-06-09', 'cleared'
            )
            """,
            (ctx["inactive_company_account_id"], ctx["active_vendor_account_id"]),
        )


def test_schema_rejects_direct_vendor_advance_with_inactive_vendor_account(
    purchase_bank_validation_db,
):
    ctx = purchase_bank_validation_db

    with pytest.raises(sqlite3.IntegrityError, match="vendor bank account is inactive"):
        ctx["conn"].execute(
            """
            INSERT INTO vendor_advances (
                vendor_id, tx_date, amount, source_type, method, bank_account_id,
                vendor_bank_account_id, instrument_type, instrument_no, clearing_state
            ) VALUES (?, '2026-06-09', 10, 'deposit', 'Bank Transfer', ?, ?, 'online', 'TXN-1', 'cleared')
            """,
            (
                ctx["vendor_id"],
                ctx["active_company_account_id"],
                ctx["inactive_vendor_account_id"],
            ),
        )
