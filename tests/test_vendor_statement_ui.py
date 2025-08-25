# inventory_management/tests/test_vendor_statement_ui.py
from __future__ import annotations

import sqlite3
import pytest

from inventory_management.modules.vendor.controller import VendorController
from inventory_management.database.repositories.purchases_repo import (
    PurchasesRepo, PurchaseHeader, PurchaseItem
)
from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo
)
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo
)


def _new_purchase_id(con: sqlite3.Connection, date_str: str) -> str:
    """Match controller’s ID scheme: POYYYYMMDD-#### (max+1 within day)."""
    d = date_str.replace("-", "")
    prefix = f"PO{d}-"
    row = con.execute(
        "SELECT MAX(purchase_id) AS m FROM purchases WHERE purchase_id LIKE ?;",
        (prefix + "%",),
    ).fetchone()
    last = 0
    if row and row["m"]:
        try:
            last = int(str(row["m"]).split("-")[-1])
        except Exception:
            last = 0
    return f"{prefix}{last+1:04d}"


@pytest.mark.usefixtures("app")  # ensure QApplication via pytest-qt
def test_e_vendor_statement_composition_ui(conn: sqlite3.Connection, ids: dict, qtbot):
    """
    Suite E — Vendor Controller statement (UI composition test)

    Flows:
      - Opening credit before period
      - One in-period purchase (300)
      - Cleared bank transfer (80)
      - Credit applied (50)
    Expectations:
      totals.purchases ≈ 300
      totals.cash_paid = 80
      totals.credit_applied = 50
      opening_credit ≈ 120
    """
    vendor_id = ids["vendor_id"]
    company_meezan = ids["company_meezan"]
    vendor_vba = ids["vendor_primary_vba"]

    # 0) Grant opening credit BEFORE the reporting period
    vadv = VendorAdvancesRepo(conn)
    vadv.grant_credit(vendor_id=vendor_id, amount=120.0, date="2024-12-31",
                      notes="Y/E adj", created_by=None)

    # 1) Create one purchase in period (2025-01-10), total ≈ 300
    pr = PurchasesRepo(conn)
    purchase_date = "2025-01-10"
    pid = _new_purchase_id(conn, purchase_date)

    header = PurchaseHeader(
        purchase_id=pid,
        vendor_id=vendor_id,
        date=purchase_date,
        total_amount=0.0,        # repo will recompute
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=None,
        created_by=None,
    )
    items = [
        PurchaseItem(
            item_id=None,
            purchase_id=pid,
            product_id=ids["prod_A"],
            quantity=3.0,
            uom_id=ids["uom_piece"],
            purchase_price=100.0,
            sale_price=120.0,
            item_discount=0.0,
        ),
    ]
    pr.create_purchase(header, items)

    # 2) Record a CLEARED bank transfer payment (80) inside period
    ppay = PurchasePaymentsRepo(conn)
    ppay.record_payment(
        purchase_id=pid, amount=80.0, method="Bank Transfer",
        bank_account_id=company_meezan,
        vendor_bank_account_id=vendor_vba,
        instrument_type="online", instrument_no="BT-200",
        instrument_date="2025-01-12",
        deposited_date=None, cleared_date="2025-01-12",
        clearing_state="cleared",
        ref_no=None, notes=None, date="2025-01-12", created_by=None
    )

    # 3) Apply vendor credit (50) in period
    vadv.apply_credit_to_purchase(
        vendor_id=vendor_id, purchase_id=pid, amount=50.0,
        date="2025-01-15", notes="apply credit", created_by=None
    )

    # 4) Build statement via the UI controller
    controller = VendorController(conn)
    out = controller.build_vendor_statement(
        vendor_id=vendor_id,
        date_from="2025-01-01", date_to="2025-01-31",
        include_opening=True, show_return_origins=True
    )

    # ---- Assertions (shape + totals) ----
    assert out["vendor_id"] == vendor_id
    assert out["period"]["from"] == "2025-01-01"
    assert out["period"]["to"] == "2025-01-31"
    assert isinstance(out["opening_credit"], float)
    assert isinstance(out["opening_payable"], float)
    assert set(out["totals"].keys()) == {"purchases", "cash_paid", "refunds", "credit_notes", "credit_applied"}
    assert isinstance(out["closing_balance"], float)
    assert isinstance(out["rows"], list)

    # Totals within period
    assert abs(out["totals"]["purchases"] - 300.0) < 1e-6
    assert abs(out["totals"]["cash_paid"] - 80.0) < 1e-6
    assert abs(out["totals"]["credit_applied"] - 50.0) < 1e-6

    # Opening credit is the deposit before the period
    assert abs(out["opening_credit"] - 120.0) < 1e-6
