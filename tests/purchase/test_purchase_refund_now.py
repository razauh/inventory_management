import sqlite3

import pytest

from inventory_management.database.repositories.dashboard_repo import DashboardRepo
from inventory_management.database.repositories.purchase_payments_repo import PurchasePaymentsRepo
from inventory_management.database.repositories.purchases_repo import PurchasesRepo
from inventory_management.database.repositories.vendor_advances_repo import VendorAdvancesRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.purchase.return_form import PurchaseReturnForm
from inventory_management.modules.vendor.controller import VendorController


PURCHASE_ID = "PO-REFUND-NOW"


@pytest.fixture()
def refund_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    conn.execute(
        "INSERT INTO company_info (company_id, company_name) VALUES (1, 'Test Company')"
    )
    user_id = conn.execute(
        """
        INSERT INTO users (username, password_hash, full_name)
        VALUES ('refund-user', 'hash', 'Refund User')
        """
    ).lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Refund Vendor', 'Test')"
    ).lastrowid
    company_account_id = conn.execute(
        """
        INSERT INTO company_bank_accounts (company_id, label)
        VALUES (1, 'Refund Receiving Account')
        """
    ).lastrowid
    vendor_account_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no)
        VALUES (?, 'Vendor Source Account', 'Test Bank', 'V-100')
        """,
        (vendor_id,),
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Refund Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, payment_status, created_by
        ) VALUES (?, ?, '2026-05-01', 100, 'unpaid', ?)
        """,
        (PURCHASE_ID, vendor_id, user_id),
    )
    item_id = conn.execute(
        """
        INSERT INTO purchase_items (
            purchase_id, product_id, quantity, uom_id,
            purchase_price, sale_price, item_discount
        ) VALUES (?, ?, 10, ?, 10, 12, 0)
        """,
        (PURCHASE_ID, product_id, uom_id),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date, txn_seq
        ) VALUES (?, 10, ?, 'purchase', 'purchases', ?, ?, '2026-05-01', 10)
        """,
        (product_id, uom_id, PURCHASE_ID, item_id),
    )

    try:
        yield {
            "conn": conn,
            "user_id": int(user_id),
            "vendor_id": int(vendor_id),
            "company_account_id": int(company_account_id),
            "vendor_account_id": int(vendor_account_id),
            "item_id": int(item_id),
        }
    finally:
        conn.close()


def _pay(conn, amount):
    PurchasePaymentsRepo(conn).record_payment(
        PURCHASE_ID,
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-05-02",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-05-02",
        created_by=None,
    )


def _settlement(db, mode="refund_now"):
    return {
        "mode": mode,
        "method": "Bank Transfer",
        "bank_account_id": db["company_account_id"],
        "vendor_bank_account_id": db["vendor_account_id"],
        "instrument_type": "online",
        "instrument_no": "REF-100",
        "instrument_date": "2026-05-10",
        "deposited_date": "2026-05-10",
        "cleared_date": "2026-05-10",
        "clearing_state": "cleared",
        "ref_no": "RETURN-100",
        "notes": "Vendor refund received",
    }


def _return(db, qty, mode="refund_now"):
    PurchasesRepo(db["conn"]).record_return(
        pid=PURCHASE_ID,
        date="2026-05-10",
        created_by=db["user_id"],
        lines=[{"item_id": db["item_id"], "qty_return": qty}],
        notes="Returned goods",
        settlement=_settlement(db, mode),
    )


def _form(qtbot, db):
    repo = PurchasesRepo(db["conn"])
    item = dict(repo.list_items(PURCHASE_ID)[0])
    item["returnable"] = 10.0
    form = PurchaseReturnForm(
        items=[item],
        vendor_id=db["vendor_id"],
        purchases_repo=repo,
    )
    qtbot.addWidget(form)
    form.set_purchase_id(PURCHASE_ID)
    return form


def test_ui_refund_now_requires_full_payment_and_respects_cash_cap(qtbot, refund_db):
    form = _form(qtbot, refund_db)
    assert not form.rb_refund_now.isEnabled()

    _pay(refund_db["conn"], 50)
    form._update_remaining_amount()
    assert not form.rb_refund_now.isEnabled()

    _pay(refund_db["conn"], 50)
    form._update_remaining_amount()
    assert form.rb_refund_now.isEnabled()

    form.tbl.item(0, form.COL_QTY_RETURN).setText("10")
    form._recalc_all()
    assert form.rb_refund_now.isEnabled()

    refund_db["conn"].execute(
        """
        INSERT INTO purchase_refunds (
            purchase_id, vendor_id, date, amount, method,
            clearing_state, cleared_date
        ) VALUES (?, ?, '2026-05-09', 20, 'Cash', 'cleared', '2026-05-09')
        """,
        (PURCHASE_ID, refund_db["vendor_id"]),
    )
    form._update_remaining_amount()
    assert not form.rb_refund_now.isEnabled()


@pytest.mark.parametrize("paid", [0, 50])
def test_repo_rejects_unsettled_refund_before_any_write(refund_db, paid):
    if paid:
        _pay(refund_db["conn"], paid)

    with pytest.raises(ValueError, match="fully settled"):
        _return(refund_db, 4)

    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM inventory_transactions WHERE transaction_type='purchase_return'"
    ).fetchone()[0] == 0
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM purchase_refunds"
    ).fetchone()[0] == 0
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM vendor_advances WHERE source_type='return_credit'"
    ).fetchone()[0] == 0


def test_fully_paid_refund_persists_metadata_and_bank_inflow(refund_db):
    _pay(refund_db["conn"], 100)
    _return(refund_db, 4)

    refund = refund_db["conn"].execute(
        "SELECT * FROM purchase_refunds WHERE purchase_id = ?", (PURCHASE_ID,)
    ).fetchone()
    assert float(refund["amount"]) == pytest.approx(40)
    assert refund["vendor_id"] == refund_db["vendor_id"]
    assert refund["method"] == "Bank Transfer"
    assert refund["bank_account_id"] == refund_db["company_account_id"]
    assert refund["vendor_bank_account_id"] == refund_db["vendor_account_id"]
    assert refund["instrument_no"] == "REF-100"
    assert refund["ref_no"] == "RETURN-100"
    assert refund["clearing_state"] == "cleared"
    assert refund["created_by"] == refund_db["user_id"]

    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM vendor_advances WHERE source_type='return_credit'"
    ).fetchone()[0] == 0
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM purchase_payments WHERE amount < 0"
    ).fetchone()[0] == 0

    for view in ("v_bank_ledger", "v_bank_ledger_ext"):
        movement = refund_db["conn"].execute(
            f"SELECT * FROM {view} WHERE src='purchase_refund' AND doc_id=?",
            (PURCHASE_ID,),
        ).fetchone()
        assert float(movement["amount_in"]) == pytest.approx(40)
        assert float(movement["amount_out"]) == pytest.approx(0)

    assert DashboardRepo(refund_db["conn"]).vendor_payments_cleared(
        "2026-05-01", "2026-05-31"
    ) == pytest.approx(60)


def test_refund_cap_accounts_for_prior_refunds_and_credit_notes(refund_db):
    _pay(refund_db["conn"], 60)
    advances = VendorAdvancesRepo(refund_db["conn"])
    advances.grant_credit(
        refund_db["vendor_id"],
        40,
        date="2026-05-02",
        notes="Advance",
        created_by=None,
    )
    advances.apply_credit_to_purchase(
        refund_db["vendor_id"],
        PURCHASE_ID,
        40,
        date="2026-05-02",
        notes="Applied advance",
        created_by=None,
    )

    _return(refund_db, 3, mode="credit_note")
    with pytest.raises(ValueError, match="remaining refundable direct payment"):
        _return(refund_db, 7)

    refunds = refund_db["conn"].execute(
        "SELECT COALESCE(SUM(amount), 0) FROM purchase_refunds"
    ).fetchone()[0]
    credits = refund_db["conn"].execute(
        """
        SELECT COALESCE(SUM(amount), 0) FROM vendor_advances
        WHERE source_type='return_credit' AND source_id=?
        """,
        (PURCHASE_ID,),
    ).fetchone()[0]
    assert float(refunds) == pytest.approx(0)
    assert float(credits) == pytest.approx(30)


def test_vendor_statement_refund_effect_and_opening_balance(refund_db):
    _pay(refund_db["conn"], 100)
    _return(refund_db, 4)

    controller = VendorController.__new__(VendorController)
    controller.conn = refund_db["conn"]
    controller.ppay = PurchasePaymentsRepo(refund_db["conn"])
    controller.vadv = VendorAdvancesRepo(refund_db["conn"])

    current = controller.build_vendor_statement(refund_db["vendor_id"])
    refund_row = next(row for row in current["rows"] if row["type"] == "Refund")
    assert refund_row["amount_effect"] == pytest.approx(40)
    assert current["closing_balance"] == pytest.approx(0)

    opening = controller.build_vendor_statement(
        refund_db["vendor_id"], date_from="2026-06-01"
    )
    assert opening["opening_payable"] == pytest.approx(0)


def test_credit_note_still_uses_vendor_credit_without_bank_movement(refund_db):
    _pay(refund_db["conn"], 100)
    _return(refund_db, 4, mode="credit_note")

    credit = refund_db["conn"].execute(
        """
        SELECT amount FROM vendor_advances
        WHERE source_type='return_credit' AND source_id=?
        """,
        (PURCHASE_ID,),
    ).fetchone()
    assert float(credit["amount"]) == pytest.approx(40)
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM purchase_refunds"
    ).fetchone()[0] == 0
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM v_bank_ledger WHERE src='purchase_refund'"
    ).fetchone()[0] == 0


def test_refund_insert_failure_rolls_back_entire_return(refund_db):
    _pay(refund_db["conn"], 100)
    refund_db["conn"].execute(
        """
        CREATE TRIGGER fail_purchase_refund_insert
        BEFORE INSERT ON purchase_refunds
        BEGIN
          SELECT RAISE(ABORT, 'forced refund failure');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced refund failure"):
        _return(refund_db, 4)

    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM inventory_transactions WHERE transaction_type='purchase_return'"
    ).fetchone()[0] == 0
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM purchase_return_snapshots"
    ).fetchone()[0] == 0
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM purchase_refunds"
    ).fetchone()[0] == 0
    assert refund_db["conn"].execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action_type IN ('return', 'refund')"
    ).fetchone()[0] == 0
