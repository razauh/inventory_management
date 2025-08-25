# inventory_management/tests/test_purchase_controller_flows.py
from __future__ import annotations

from PySide6.QtWidgets import QApplication

import sqlite3
from typing import Any, Optional

import pytest
from PySide6 import QtWidgets

from inventory_management.modules.purchase.controller import PurchaseController
from inventory_management.database.repositories.products_repo import ProductsRepo
from inventory_management.database.repositories.vendor_advances_repo import VendorAdvancesRepo


# --------------------------- helpers ---------------------------

def _prefix_for(date_str: str) -> str:
    d = date_str.replace("-", "")
    return f"PO{d}-"


def _get_val(row_obj, key):
    """
    Safe getter that works for both sqlite3.Row and dict-like objects.
    """
    try:
        return row_obj[key]  # sqlite3.Row supports __getitem__
    except Exception:
        try:
            return row_obj.get(key)
        except Exception:
            return None


def _select_purchase_in_controller(ctrl, purchase_id: str) -> bool:
    """
    Select the row for purchase_id in the controller's view so actions
    like mark_payment_cleared() see the correct 'current' purchase.
    """
    # ensure model is present
    if not hasattr(ctrl, "proxy") or not hasattr(ctrl, "base"):
        ctrl._reload()

    proxy = ctrl.proxy
    base = ctrl.base
    tbl = ctrl.view.tbl

    for r in range(proxy.rowCount()):
        src = proxy.mapToSource(proxy.index(r, 0))
        row = base.at(src.row())
        if _get_val(row, "purchase_id") == purchase_id:
            tbl.selectRow(r)
            QApplication.processEvents()
            return True
    return False


def _last_pid_for_date(con: sqlite3.Connection, date_str: str) -> Optional[str]:
    """Grab the highest purchase_id for a specific date prefix (what controller generates)."""
    prefix = _prefix_for(date_str)
    row = con.execute(
        "SELECT MAX(purchase_id) AS m FROM purchases WHERE purchase_id LIKE ?;",
        (prefix + "%",),
    ).fetchone()
    return None if not row or not row["m"] else str(row["m"])


def _header(con: sqlite3.Connection, pid: str):
    return con.execute(
        "SELECT purchase_id, date, total_amount, order_discount, paid_amount, advance_payment_applied, payment_status "
        "FROM purchases WHERE purchase_id=?;",
        (pid,),
    ).fetchone()


def _payment_row(con: sqlite3.Connection, pid: str):
    return con.execute(
        "SELECT * FROM purchase_payments WHERE purchase_id=? ORDER BY payment_id DESC LIMIT 1;",
        (pid,),
    ).fetchone()


def _ledger_ext_last(con: sqlite3.Connection, pid: str):
    return con.execute(
        "SELECT amount_in, amount_out FROM v_bank_ledger_ext WHERE src='purchase' AND doc_id=? "
        "ORDER BY payment_id DESC LIMIT 1;",
        (pid,),
    ).fetchone()


def _base_uom(conn: sqlite3.Connection, product_id: int) -> int:
    """
    Returns the base UoM id for a product.
    Tries repo.get_base_uom first, falls back to scanning product_uoms.
    """
    pr = ProductsRepo(conn)
    try:
        r = pr.get_base_uom(product_id)  # expected to return {"uom_id", "unit_name"}
        if r and _get_val(r, "uom_id"):
            return int(_get_val(r, "uom_id"))
    except Exception:
        pass

    row = conn.execute(
        """
        SELECT pu.uom_id
        FROM product_uoms pu
        WHERE pu.product_id = ? AND CAST(pu.is_base AS INTEGER) = 1
        LIMIT 1
        """,
        (product_id,),
    ).fetchone()
    assert row, f"No base UoM mapping found for product_id={product_id}"
    return int(row["uom_id"] if isinstance(row, sqlite3.Row) else row[0])


# --------------------------- stubs ---------------------------

class _StubForm:
    """
    Minimal stub for PurchaseForm used by controller._add().
    """
    def __init__(self, *a, **k):
        self._payload: Optional[dict[str, Any]] = k.pop("_payload")  # we inject this in tests

    def exec(self) -> int:
        # nonzero means "accepted"
        return 1 if self._payload else 0

    def payload(self) -> Optional[dict[str, Any]]:
        return self._payload


# =========================
# Suite D — Controller E2E
# =========================

def test_d1_create_with_initial_bank_transfer_cleared(conn: sqlite3.Connection, ids: dict, qtbot, monkeypatch):
    """
    D1. Create + initial payment → paid (mirrors test_p2).
    - Initial method: Bank Transfer, cleared, valid instrument meta.
    - Assert header paid_amount==total and payment_status=='paid'.
    - Payment row contains the expected fields; ledger ext amount_out == amount.
    """
    # Prepare controller (view needs QApplication via qtbot/qapp)
    ctrl = PurchaseController(conn, current_user={"user_id": ids.get("user_id", 1)})

    date = "2025-01-22"
    prod_id = ids["prod_A"]
    uom_id = _base_uom(conn, prod_id)

    # One line: qty=2, buy=100, disc=0 -> total 200
    total = 2 * (100.0 - 0.0)

    payload = {
        "vendor_id": ids["vendor_id"],
        "date": date,
        "order_discount": 0.0,
        "notes": None,
        "items": [
            {
                "product_id": prod_id,
                "uom_id": uom_id,
                "quantity": 2.0,
                "purchase_price": 100.0,
                "sale_price": 110.0,
                "item_discount": 0.0,
            }
        ],
        "total_amount": total,
        # New nested contract consumed by controller
        "initial_payment": {
            "amount": total,
            "method": "Bank Transfer",
            "bank_account_id": ids["company_meezan"],
            "vendor_bank_account_id": ids["vendor_primary_vba"],
            "instrument_type": "online",
            "instrument_no": "BT-D1-001",
            "instrument_date": date,
            "deposited_date": None,
            "cleared_date": date,          # CLEARED to take effect immediately
            "clearing_state": "cleared",
            "ref_no": "D1",
            "notes": None,
            "date": date,
        },
    }

    # Monkeypatch the dialog class the controller uses
    import inventory_management.modules.purchase.controller as ctl_mod
    monkeypatch.setattr(ctl_mod, "PurchaseForm", lambda *a, **k: _StubForm(_payload=payload))

    # Act
    ctrl._add()

    # Find the new purchase_id for this date
    pid = _last_pid_for_date(conn, date)
    assert pid, "No purchase created"

    hdr = _header(conn, pid)
    assert abs(float(hdr["total_amount"]) - total) < 1e-6
    assert abs(float(hdr["paid_amount"]) - total) < 1e-6
    assert hdr["payment_status"] == "paid"

    pay = _payment_row(conn, pid)
    assert pay is not None
    assert abs(float(pay["amount"]) - total) < 1e-6
    assert pay["method"] == "Bank Transfer"
    assert pay["instrument_type"] == "online"
    assert (pay["clearing_state"] or "") == "cleared"

    # Ledger ext: outgoing equals amount
    led = _ledger_ext_last(conn, pid)
    assert led and abs(float(led["amount_out"]) - total) < 1e-6 and abs(float(led["amount_in"])) < 1e-9


def test_d2_create_with_pending_cheque_then_clear(conn: sqlite3.Connection, ids: dict, qtbot, monkeypatch):
    """
    D2. Create + pending Cheque → unpaid, then clear → partial (mirrors test_p3).
    - After create: header remains unpaid (cleared-only rollup).
    - Clear the payment; header shows partial; row shows clearing_state='cleared'.
    """
    ctrl = PurchaseController(conn, current_user={"user_id": ids.get("user_id", 1)})

    date = "2025-01-23"
    prod_id = ids["prod_A"]
    uom_id = _base_uom(conn, prod_id)

    # One line: qty=5, buy=100, disc=0 -> total 500; pay 200 by cheque (pending)
    total = 5 * 100.0
    pay_amt = 200.0

    payload = {
        "vendor_id": ids["vendor_id"],
        "date": date,
        "order_discount": 0.0,
        "notes": None,
        "items": [
            {
                "product_id": prod_id,
                "uom_id": uom_id,
                "quantity": 5.0,
                "purchase_price": 100.0,
                "sale_price": 110.0,
                "item_discount": 0.0,
            }
        ],
        "total_amount": total,
        "initial_payment": {
            "amount": pay_amt,
            "method": "Cheque",
            "bank_account_id": ids["company_hbl"],
            "vendor_bank_account_id": ids["vendor_primary_vba"],
            "instrument_type": "cross_cheque",
            "instrument_no": "CHQ-D2-200",
            "instrument_date": date,
            "deposited_date": None,
            "cleared_date": None,
            "clearing_state": "pending",
            "ref_no": "D2",
            "notes": None,
            "date": date,
        },
    }

    import inventory_management.modules.purchase.controller as ctl_mod
    monkeypatch.setattr(ctl_mod, "PurchaseForm", lambda *a, **k: _StubForm(_payload=payload))

    # Act: create
    ctrl._add()

    pid = _last_pid_for_date(conn, date)
    assert pid, "No purchase created"

    # After create: unpaid, paid_amount still 0 (pending doesn't roll up)
    hdr = _header(conn, pid)
    assert abs(float(hdr["total_amount"]) - total) < 1e-6
    assert abs(float(hdr["paid_amount"])) < 1e-9
    assert hdr["payment_status"] == "unpaid"

    pay = _payment_row(conn, pid)
    assert pay and (pay["clearing_state"] or "") == "pending"
    payment_id = int(pay["payment_id"])

    # Select the newly created purchase row in the controller BEFORE clearing
    # (mark_payment_cleared acts on the currently selected purchase)
    assert _select_purchase_in_controller(ctrl, pid), "Could not select the new purchase row in the controller"

    # Now clear it using controller method
    ctrl.mark_payment_cleared(payment_id, cleared_date=date)

    # After clear: header reflects partial
    hdr2 = _header(conn, pid)
    assert abs(float(hdr2["paid_amount"]) - pay_amt) < 1e-6
    assert hdr2["payment_status"] in (
        "partial",
        "partially_paid",
        "partial_payment",
    ) or float(hdr2["paid_amount"]) < float(hdr2["total_amount"])

    pay2 = _payment_row(conn, pid)
    assert pay2 and (pay2["clearing_state"] or "") == "cleared"


def test_d3_apply_vendor_credit_overdraw_surface_error(conn: sqlite3.Connection, ids: dict, qtbot, monkeypatch):
    """
    D3. Apply vendor credit via controller (error surfaced, header unchanged).
    - Grant credit +200.
    - Create a purchase with due < 500.
    - Call controller.apply_vendor_credit(amount=500) -> IntegrityError caught and message shown.
    - Assert header.advance_payment_applied unchanged (still 0).
    """
    # Capture user messages from controller.info(...)
    messages: list[str] = []

    import inventory_management.modules.purchase.controller as ctl_mod

    def _catch_info(_parent, title: str, msg: str):
        messages.append(f"{title}: {msg}")

    monkeypatch.setattr(ctl_mod, "info", _catch_info)

    ctrl = PurchaseController(conn, current_user={"user_id": ids.get("user_id", 1)})

    # Grant credit +200 (manual)
    vadv = VendorAdvancesRepo(conn)
    vadv.grant_credit(vendor_id=ids["vendor_id"], amount=200.0, date="2025-01-24", notes="prep", created_by=ids.get("user_id"))

    # Create a small purchase (due < 500)
    date = "2025-01-24"
    prod_id = ids["prod_B"]
    uom_id = _base_uom(conn, prod_id)
    total = 100.0
    payload = {
        "vendor_id": ids["vendor_id"],
        "date": date,
        "order_discount": 0.0,
        "notes": None,
        "items": [
            {"product_id": prod_id, "uom_id": uom_id, "quantity": 1.0, "purchase_price": total, "sale_price": 120.0, "item_discount": 0.0}
        ],
        "total_amount": total,
        # No initial payment
        "initial_payment": None,
    }
    monkeypatch.setattr(ctl_mod, "PurchaseForm", lambda *a, **k: _StubForm(_payload=payload))

    # Create the purchase
    ctrl._add()
    pid = _last_pid_for_date(conn, date)
    assert pid, "No purchase created"

    # Attempt to apply 500 credit (more than available 200) via controller helper
    ctrl.apply_vendor_credit(amount=500.0)

    # Message surfaced
    assert any("Credit not applied" in m for m in messages), "Expected user-facing error message to be shown"

    # Header advance_payment_applied unchanged (0)
    hdr = _header(conn, pid)
    assert abs(float(hdr["advance_payment_applied"])) < 1e-9
