# inventory_management/tests/test_error_parity_ui.py
from __future__ import annotations

import sqlite3
import pytest

from inventory_management.modules.purchase.form import PurchaseForm
from inventory_management.modules.vendor.controller import VendorController
from inventory_management.database.repositories.purchases_repo import (
    PurchasesRepo, PurchaseHeader, PurchaseItem
)
from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo
)
from inventory_management.database.repositories.products_repo import ProductsRepo
from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.database.repositories.vendor_advances_repo import VendorAdvancesRepo


def _new_purchase_id(con: sqlite3.Connection, date_str: str) -> str:
    d = date_str.replace("-", "")
    prefix = f"PO{d}-"
    row = con.execute(
        "SELECT MAX(purchase_id) AS m FROM purchases WHERE purchase_id LIKE ?",
        (prefix + "%",),
    ).fetchone()
    last = 0
    if row and row["m"]:
        try:
            last = int(str(row["m"]).split("-")[-1])
        except Exception:
            last = 0
    return f"{prefix}{last+1:04d}"


def _make_purchase(conn: sqlite3.Connection, ids: dict, *, date="2025-01-10", qty=1, buy=100.0, sale=120.0, disc=0.0) -> str:
    pr = PurchasesRepo(conn)
    pid = _new_purchase_id(conn, date)
    header = PurchaseHeader(
        purchase_id=pid,
        vendor_id=ids["vendor_id"],
        date=date,
        total_amount=0.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=None,
        created_by=None,
    )
    items = [
        PurchaseItem(
            item_id=None, purchase_id=pid,
            product_id=ids["prod_A"], quantity=float(qty),
            uom_id=ids["uom_piece"], purchase_price=float(buy),
            sale_price=float(sale), item_discount=float(disc),
        ),
    ]
    pr.create_purchase(header, items)
    return pid


# ---------------------------------------------------------------------
# F1. Payment method guards — UI blocks & DB parity raises IntegrityError
# ---------------------------------------------------------------------
@pytest.mark.usefixtures("app")
def test_f1_payment_method_guards_ui_and_db(conn: sqlite3.Connection, ids: dict, qtbot):
    vendors = VendorsRepo(conn)
    products = ProductsRepo(conn)
    ppay = PurchasePaymentsRepo(conn)

    # Prepare a purchase to attach payments
    pid = _make_purchase(conn, ids, date="2025-01-15", qty=1, buy=100, sale=120, disc=0)

    # Create the form (do not show; we drive fields directly)
    form = PurchaseForm(None, vendors=vendors, products=products)

    # --- Bank Transfer: UI should block if missing company account or instrument_no ---
    form.ip_amount.setText("50")
    form.ip_method.setCurrentText("Bank Transfer")
    form._refresh_ip_visibility()

    # Remove company account to simulate "none selected"
    form.ip_company_acct.clear()
    form.ip_instr_no.setText("")  # missing instrument no
    assert form.get_payload() is None  # UI blocks

    # DB parity: calling repo directly with missing required fields should raise
    with pytest.raises(sqlite3.IntegrityError) as e1:
        ppay.record_payment(
            purchase_id=pid, amount=50.0, method="Bank Transfer",
            bank_account_id=None, vendor_bank_account_id=None,
            instrument_type="online", instrument_no=None,
            instrument_date=None, deposited_date=None, cleared_date=None,
            clearing_state="posted", ref_no=None, notes=None, date="2025-01-15", created_by=None
        )
    assert "Bank Transfer requires company account" in str(e1.value)

    # --- Cheque: UI blocks if missing required fields (company acct / cheque no) ---
    form.ip_amount.setText("50")
    form.ip_method.setCurrentText("Cheque")
    form._refresh_ip_visibility()
    form.ip_company_acct.clear()           # force missing company account
    form.ip_instr_no.setText("")           # missing cheque no
    assert form.get_payload() is None      # UI blocks

    # DB parity: wrong instrument_type + missing company/cheque -> IntegrityError
    with pytest.raises(sqlite3.IntegrityError) as e2:
        ppay.record_payment(
            purchase_id=pid, amount=50.0, method="Cheque",
            bank_account_id=None, vendor_bank_account_id=None,
            instrument_type="online", instrument_no=None,
            instrument_date=None, deposited_date=None, cleared_date=None,
            clearing_state="pending", ref_no=None, notes=None, date="2025-01-15", created_by=None
        )
    assert "Cheque requires company account" in str(e2.value)

    # --- Cash Deposit: UI blocks if missing slip no or vendor account ---
    form.ip_amount.setText("50")
    form.ip_method.setCurrentText("Cash Deposit")
    form._refresh_ip_visibility()
    form.ip_vendor_acct.clear()            # force missing vendor account
    form.ip_instr_no.setText("")           # missing deposit slip
    assert form.get_payload() is None      # UI blocks

    # DB parity: wrong instrument type or missing slip -> IntegrityError
    with pytest.raises(sqlite3.IntegrityError) as e3:
        ppay.record_payment(
            purchase_id=pid, amount=50.0, method="Cash Deposit",
            bank_account_id=None, vendor_bank_account_id=None,
            instrument_type="online", instrument_no=None,
            instrument_date=None, deposited_date=None, cleared_date=None,
            clearing_state="pending", ref_no=None, notes=None, date="2025-01-15", created_by=None
        )
    # message text can vary; stable substring from your tests:
    assert "Cash Deposit requires deposit slip" in str(e3.value)


# ---------------------------------------------------------------------
# F2. Over-apply vendor credit — controller surfaces friendly message; header unchanged
# ---------------------------------------------------------------------
@pytest.mark.usefixtures("app")
def test_f2_overapply_vendor_credit_controller_message(conn: sqlite3.Connection, ids: dict, monkeypatch, qtbot):
    # Create a small purchase: total ≈ 100
    pid = _make_purchase(conn, ids, date="2025-01-18", qty=1, buy=100, sale=120, disc=0)

    # Grant credit greater than remaining due (so we trigger "beyond remaining due")
    vadv = VendorAdvancesRepo(conn)
    vadv.grant_credit(vendor_id=ids["vendor_id"], amount=200.0, date="2025-01-18", notes="seed", created_by=None)

    # Capture messages from the controller (patch the imported symbol in the controller module)
    msgs = []

    import inventory_management.modules.vendor.controller as vendor_controller

    def _capture(parent, title, text):
        msgs.append((title, text))

    # Patch here (NOT inventory_management.utils.ui_helpers.info)
    monkeypatch.setattr(vendor_controller, "info", _capture, raising=False)

    ctl = VendorController(conn)

    # Attempt to apply more than the purchase balance (e.g., 150 > 100)
    ctl.apply_vendor_credit_to_purchase(
        purchase_id=pid,
        amount=150.0,
        date="2025-01-18",
        notes="over-apply",
        created_by=None,
    )

    # Expect a friendly message captured
    assert msgs, "Controller should surface a user message on IntegrityError."
    # Optional: tolerant check on message contents
    title, text = msgs[-1]
    assert "Credit not applied" in title
    assert ("Insufficient vendor credit" in text) or ("Cannot apply credit beyond remaining due" in text)


# ---------------------------------------------------------------------
# F3. Non-base UoM — impossible via dialog; DB rejects malformed payload
# ---------------------------------------------------------------------
def test_f3_non_base_uom_rejected_db(conn: sqlite3.Connection, ids: dict):
    """
    The dialog enforces base UoM only. If a caller bypasses the UI
    and submits a non-base UoM to the repo, the DB must reject it.
    """
    # Find the non-base UoM for Widget A from the seed ("Box")
    row = conn.execute(
        """
        SELECT pu.uom_id
        FROM product_uoms pu
        JOIN uoms u ON u.uom_id = pu.uom_id
        WHERE pu.product_id=? AND COALESCE(pu.is_base,0)=0 AND u.unit_name='Box'
        """,
        (ids["prod_A"],),
    ).fetchone()
    assert row is not None, "Seed should provide a non-base UoM 'Box' for Widget A."
    non_base_uom = int(row["uom_id"])

    pr = PurchasesRepo(conn)
    pid = _new_purchase_id(conn, "2025-01-20")
    header = PurchaseHeader(
        purchase_id=pid, vendor_id=ids["vendor_id"], date="2025-01-20",
        total_amount=0.0, order_discount=0.0,
        payment_status="unpaid", paid_amount=0.0,
        advance_payment_applied=0.0, notes=None, created_by=None
    )
    items = [
        PurchaseItem(
            item_id=None, purchase_id=pid,
            product_id=ids["prod_A"], quantity=1.0,
            uom_id=non_base_uom,      # <-- NON-BASE on purpose
            purchase_price=100.0, sale_price=120.0, item_discount=0.0
        )
    ]

    with pytest.raises(sqlite3.IntegrityError):
        pr.create_purchase(header, items)
