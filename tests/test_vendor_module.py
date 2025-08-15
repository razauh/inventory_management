# tests/test_vendor_module.py
import sqlite3
from pathlib import Path
import datetime as dt
import pytest

# --- Project imports (adjust if your package layout differs) ---
from inventory_management.database.repositories.purchases_repo import (
    PurchasesRepo, PurchaseHeader, PurchaseItem
)
from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo
)
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo
)
from inventory_management.database.repositories.vendor_bank_accounts_repo import (
    VendorBankAccountsRepo
)

# Optional (only used in V6 — controller composition)
try:
    from PySide6.QtWidgets import QApplication
    from inventory_management.modules.vendor.controller import VendorController
    HAVE_QT = True
except Exception:
    HAVE_QT = False


# -------------------------
# Fixtures & small helpers
# -------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "myshop.db"
SEED_SQL = PROJECT_ROOT / "tests" / "seed_common.sql"

@pytest.fixture(scope="session", autouse=True)
def apply_common_seed():
    """Run the idempotent seed once per test session."""
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("PRAGMA foreign_keys=ON;")
        con.executescript(SEED_SQL.read_text())
        con.commit()
    finally:
        con.close()

@pytest.fixture()
def conn():
    """Connection with FK on and row access by name; each test rolled back."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    # Start a transaction and rollback at end to keep DB clean
    con.execute("BEGIN;")
    try:
        yield con
        con.rollback()
    finally:
        con.close()

@pytest.fixture()
def ids(conn):
    """Common lookups."""
    def one(sql, *p):
        r = conn.execute(sql, p).fetchone()
        return None if r is None else (r[0] if not isinstance(r, sqlite3.Row) else list(r)[0])
    vendor_id = one("SELECT vendor_id FROM vendors WHERE name='Vendor X' LIMIT 1")
    v_primary = conn.execute(
        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE vendor_id=? AND is_primary=1",
        (vendor_id,)
    ).fetchone()
    company_meezan = one("SELECT account_id FROM company_bank_accounts WHERE label='Meezan — Current' LIMIT 1")
    company_hbl    = one("SELECT account_id FROM company_bank_accounts WHERE label='HBL — Current' LIMIT 1")
    return {
        "vendor_id": vendor_id,
        "vendor_primary_vba": (None if v_primary is None else int(v_primary[0])),
        "company_meezan": company_meezan,
        "company_hbl": company_hbl,
        "uom_piece": one("SELECT uom_id FROM uoms WHERE unit_name='Piece'"),
        "prod_A": one("SELECT product_id FROM products WHERE name='Widget A'"),
        "prod_B": one("SELECT product_id FROM products WHERE name='Widget B'"),
    }

def new_purchase_id(con: sqlite3.Connection, date_str: str) -> str:
    d = date_str.replace("-", "")
    prefix = f"PO{d}-"
    row = con.execute(
        "SELECT MAX(purchase_id) AS m FROM purchases WHERE purchase_id LIKE ?",
        (prefix + "%",)
    ).fetchone()
    last = 0
    if row and row["m"]:
        try:
            last = int(str(row["m"]).split("-")[-1])
        except Exception:
            last = 0
    return f"{prefix}{last+1:04d}"

def make_purchase(conn, ids, date, items_spec):
    """
    Create a purchase via PurchasesRepo so inventory rows/txn_seq are correct.
    items_spec: list of dicts with keys (product_id, uom_id, quantity, purchase_price, sale_price, item_discount)
    Returns purchase_id.
    """
    pr = PurchasesRepo(conn)
    pid = new_purchase_id(conn, date)
    header = PurchaseHeader(
        purchase_id=pid,
        vendor_id=ids["vendor_id"],
        date=date,
        total_amount=0.0,           # will be recomputed in repo
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
            product_id=it["product_id"], quantity=it["quantity"],
            uom_id=it["uom_id"], purchase_price=it["purchase_price"],
            sale_price=it["sale_price"], item_discount=it.get("item_discount", 0.0)
        )
        for it in items_spec
    ]
    pr.create_purchase(header, items)
    return pid


# =========================
# V1 — Vendor bank accounts
# =========================
def test_v1_vendor_bank_accounts_crud(conn, ids):
    repo = VendorBankAccountsRepo(conn)

    # Create a second account for Vendor X
    acc2_id = repo.create(ids["vendor_id"], {
        "label": "VendorX — Meezan",
        "bank_name": "Meezan",
        "account_no": "V-222",
        "iban": None,
        "routing_no": None,
        "is_primary": 0,
        "is_active": 1,
    })
    assert isinstance(acc2_id, int)

    # Unique labels per vendor: re-inserting same label should violate unique index
    with pytest.raises(sqlite3.IntegrityError):
        repo.create(ids["vendor_id"], {
            "label": "VendorX — Meezan",
            "bank_name": "Meezan",
            "account_no": "V-333",
            "iban": None,
            "routing_no": None,
            "is_primary": 0,
            "is_active": 1,
        })

    # One primary per vendor: try setting both to primary=1
    # First ensure existing primary is 1
    prim_id = ids["vendor_primary_vba"]
    assert prim_id is not None
    # Then attempt to mark the second also primary -> should fail due to partial unique index
    with pytest.raises(sqlite3.IntegrityError):
        repo.set_primary(ids["vendor_id"], acc2_id)

    # Create a purchase + payment referencing acc2_id, then deactivate acc2_id (should be allowed)
    pid = make_purchase(conn, ids, "2025-01-05", [{
        "product_id": ids["prod_A"], "uom_id": ids["uom_piece"],
        "quantity": 2, "purchase_price": 100.0, "sale_price": 120.0, "item_discount": 0.0
    }])
    ppay = PurchasePaymentsRepo(conn)
    ppay.record_payment(
        purchase_id=pid, amount=50.0, method="Bank Transfer",
        bank_account_id=ids["company_meezan"],
        vendor_bank_account_id=acc2_id,
        instrument_type="online", instrument_no="BT-001",
        instrument_date="2025-01-05",
        deposited_date=None, cleared_date=None,
        clearing_state="posted",
        ref_no="T1", notes=None, date="2025-01-05", created_by=None
    )

    # Deactivate the referenced vendor account (should not fail; no delete of FK)
    affected = repo.deactivate(acc2_id)
    assert affected == 1
    row = conn.execute(
        "SELECT is_active FROM vendor_bank_accounts WHERE vendor_bank_account_id=?",
        (acc2_id,)
    ).fetchone()
    assert int(row["is_active"]) == 0

    # Verify list
    rows = conn.execute(
        "SELECT vendor_id, label, is_primary, is_active FROM vendor_bank_accounts WHERE vendor_id=? ORDER BY label",
        (ids["vendor_id"],)
    ).fetchall()
    assert len(rows) >= 2


# ==================================
# V2 — Vendor advances ledger flows
# ==================================
def test_v2_vendor_advances_basic(conn, ids):
    vadv = VendorAdvancesRepo(conn)

    # Grant credit (manual) — now defaults to source_type='deposit' (not a return).
    tx_id = vadv.grant_credit(
        vendor_id=ids["vendor_id"], amount=500.0,
        date="2025-01-11", notes="Manual credit grant", created_by=None
    )
    assert isinstance(tx_id, int)

    # Create an open purchase and apply 300 credit to it
    pid = make_purchase(conn, ids, "2025-01-12", [{
        "product_id": ids["prod_A"], "uom_id": ids["uom_piece"],
        "quantity": 3, "purchase_price": 100.0, "sale_price": 120.0, "item_discount": 0.0
    }])
    vadv.apply_credit_to_purchase(
        vendor_id=ids["vendor_id"], purchase_id=pid, amount=300.0,
        date="2025-01-13", notes="Apply credit", created_by=None
    )

    # Overdraw attempt — try to apply 1000 (should raise due to trigger)
    with pytest.raises(sqlite3.IntegrityError) as ei:
        vadv.apply_credit_to_purchase(
            vendor_id=ids["vendor_id"], purchase_id=pid, amount=1000.0,
            date="2025-01-13", notes="Overapply", created_by=None
        )
    msg = str(ei.value)
    assert ("Insufficient vendor credit" in msg) or ("Cannot apply credit beyond remaining due" in msg)

    # Verify balances/ledger
    bal = vadv.get_balance(ids["vendor_id"])
    # Started +500, applied -300 → remaining +200 (exact match allowing float)
    assert abs(bal - 200.0) < 1e-6

    ledger = vadv.list_ledger(ids["vendor_id"], ("2025-01-01", "2025-12-31"))
    # Expect a manual deposit entry and an applied_to_purchase entry
    assert any(r["source_type"] == "deposit" for r in ledger)
    assert any(r["source_type"] == "applied_to_purchase" for r in ledger)


# ============================================
# V3 — Payment method trigger rule enforcement
# ============================================
def test_v3_payment_method_rules(conn, ids):
    ppay = PurchasePaymentsRepo(conn)
    # Create a purchase to attach payments
    pid = make_purchase(conn, ids, "2025-01-15", [{
        "product_id": ids["prod_A"], "uom_id": ids["uom_piece"],
        "quantity": 1, "purchase_price": 100.0, "sale_price": 120.0, "item_discount": 0.0
    }])

    # Bank Transfer missing company bank account and/or instrument_no
    with pytest.raises(sqlite3.IntegrityError) as e1:
        ppay.record_payment(
            purchase_id=pid, amount=50.0, method="Bank Transfer",
            bank_account_id=None, vendor_bank_account_id=None,
            instrument_type="online", instrument_no=None,
            instrument_date=None, deposited_date=None, cleared_date=None,
            clearing_state="posted", ref_no=None, notes=None, date="2025-01-15", created_by=None
        )
    assert "Bank Transfer requires company account" in str(e1.value)

    # Cheque wrong instrument_type + missing company account and cheque no
    with pytest.raises(sqlite3.IntegrityError) as e2:
        ppay.record_payment(
            purchase_id=pid, amount=50.0, method="Cheque",
            bank_account_id=None, vendor_bank_account_id=None,
            instrument_type="online", instrument_no=None,
            instrument_date=None, deposited_date=None, cleared_date=None,
            clearing_state="posted", ref_no=None, notes=None, date="2025-01-15", created_by=None
        )
    assert "Cheque requires company account" in str(e2.value)

    # Cash Deposit without slip no or wrong instrument type
    with pytest.raises(sqlite3.IntegrityError) as e3:
        ppay.record_payment(
            purchase_id=pid, amount=50.0, method="Cash Deposit",
            bank_account_id=None, vendor_bank_account_id=None,
            instrument_type="online", instrument_no=None,
            instrument_date=None, deposited_date=None, cleared_date=None,
            clearing_state="posted", ref_no=None, notes=None, date="2025-01-15", created_by=None
        )
    assert "Cash Deposit requires deposit slip" in str(e3.value)

    # Outgoing via bank to vendor without vendor_bank_account_id (Bank Transfer)
    with pytest.raises(sqlite3.IntegrityError) as e4:
        ppay.record_payment(
            purchase_id=pid, amount=50.0, method="Bank Transfer",
            bank_account_id=ids["company_meezan"], vendor_bank_account_id=None,
            instrument_type="online", instrument_no="BT-XYZ",
            instrument_date="2025-01-15", deposited_date=None, cleared_date=None,
            clearing_state="posted", ref_no=None, notes=None, date="2025-01-15", created_by=None
        )
    assert "vendor account required for outgoing" in str(e4.value)


# =========================================
# V4 — Refunds (negative amounts) & clamps
# =========================================
def test_v4_refunds_negative_amounts(conn, ids):
    ppay = PurchasePaymentsRepo(conn)

    pid = make_purchase(conn, ids, "2025-01-16", [{
        "product_id": ids["prod_A"], "uom_id": ids["uom_piece"],
        "quantity": 1, "purchase_price": 100.0, "sale_price": 120.0, "item_discount": 0.0
    }])

    # Pay +50 first (valid bank transfer)
    ppay.record_payment(
        purchase_id=pid, amount=50.0, method="Bank Transfer",
        bank_account_id=ids["company_meezan"],
        vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="online", instrument_no="BT-100",
        instrument_date="2025-01-16", deposited_date=None, cleared_date=None,
        clearing_state="posted", ref_no="P50", notes=None, date="2025-01-16", created_by=None
    )

    # Then refund -100 (incoming). For negative amount, vendor_bank_account_id is NOT required.
    ppay.record_payment(
        purchase_id=pid, amount=-100.0, method="Bank Transfer",
        bank_account_id=ids["company_meezan"],
        vendor_bank_account_id=None,
        instrument_type="online", instrument_no="BT-R100",
        instrument_date="2025-01-16", deposited_date=None, cleared_date=None,
        clearing_state="posted", ref_no="R100", notes=None, date="2025-01-16", created_by=None
    )

    paid = conn.execute("SELECT CAST(paid_amount AS REAL) AS p FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
    # Clamp at >= 0 (50 + (-100) -> 0)
    assert abs(float(paid["p"]) - 0.0) < 1e-6

    # Bank ledger ext: last payment for this purchase should be incoming 100
    row = conn.execute(
        """
        SELECT amount_in, amount_out
        FROM v_bank_ledger_ext
        WHERE src='purchase' AND doc_id=?
        ORDER BY payment_id DESC LIMIT 1
        """,
        (pid,)
    ).fetchone()
    assert abs(float(row["amount_in"]) - 100.0) < 1e-6
    assert abs(float(row["amount_out"])) < 1e-6


# =============================================
# V5 — Pending instruments list & state changes
# =============================================
def test_v5_pending_and_clearing(conn, ids):
    ppay = PurchasePaymentsRepo(conn)

    pid = make_purchase(conn, ids, "2025-01-17", [{
        "product_id": ids["prod_B"], "uom_id": ids["uom_piece"],
        "quantity": 2, "purchase_price": 50.0, "sale_price": 80.0, "item_discount": 0.0
    }])

    # Cheque (pending)
    chq_id = ppay.record_payment(
        purchase_id=pid, amount=60.0, method="Cheque",
        bank_account_id=ids["company_hbl"], vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="cross_cheque", instrument_no="CHQ-777",
        instrument_date="2025-01-17", deposited_date=None, cleared_date=None,
        clearing_state="pending", ref_no=None, notes=None, date="2025-01-17", created_by=None
    )

    # Cash Deposit (pending)
    dep_id = ppay.record_payment(
        purchase_id=pid, amount=40.0, method="Cash Deposit",
        bank_account_id=None, vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="cash_deposit", instrument_no="SLIP-123",
        instrument_date="2025-01-17", deposited_date=None, cleared_date=None,
        clearing_state="pending", ref_no=None, notes=None, date="2025-01-17", created_by=None
    )

    # List pending instruments (repo optional helper)
    # We implemented list_pending_instruments(vendor_id)
    pending = ppay.list_pending_instruments(ids["vendor_id"])
    found = {r["payment_id"] for r in pending}
    assert chq_id in found and dep_id in found

    # Clear cheque, bounce deposit
    ppay.update_clearing_state(chq_id, clearing_state="cleared", cleared_date="2025-01-20")
    ppay.update_clearing_state(dep_id,  clearing_state="bounced", cleared_date="2025-01-20")

    rows = conn.execute(
        """
        SELECT pp.payment_id, pp.method, pp.instrument_no, pp.clearing_state
        FROM purchase_payments pp
        JOIN purchases p ON p.purchase_id = pp.purchase_id
        WHERE p.vendor_id=?
        AND pp.payment_id IN (?,?)
        ORDER BY pp.payment_id
        """,
        (ids["vendor_id"], chq_id, dep_id)
    ).fetchall()
    states = {r["payment_id"]: r["clearing_state"] for r in rows}
    assert states[chq_id] == "cleared"
    assert states[dep_id]  == "bounced"


# =========================================================
# V6 — Statement composition (controller orchestration)
# =========================================================
@pytest.mark.skipif(not HAVE_QT, reason="PySide6/QT not available in test environment")
def test_v6_vendor_statement_composition(conn, ids, monkeypatch):
    """
    This assumes you implemented VendorController.build_vendor_statement(...) as specified.
    We create a small period with purchases/cash/credit to verify the normalized structure.
    """
    # Minimal Qt app to allow QWidget construction inside controller
    app = QApplication.instance() or QApplication([])

    # Build a few docs in the period
    # Purchase 1: 2025-01-08 (outside reporting window, contributes to opening via credit if applied)
    pid0 = make_purchase(conn, ids, "2024-12-30", [{
        "product_id": ids["prod_A"], "uom_id": ids["uom_piece"],
        "quantity": 5, "purchase_price": 20.0, "sale_price": 25.0, "item_discount": 0.0
    }])

    # Grant vendor credit before the period (opening_credit)
    vadv = VendorAdvancesRepo(conn)
    vadv.grant_credit(ids["vendor_id"], amount=120.0, date="2024-12-31", notes="Y/E adj", created_by=None)

    # Purchase 2: in period
    pid1 = make_purchase(conn, ids, "2025-01-10", [{
        "product_id": ids["prod_A"], "uom_id": ids["uom_piece"],
        "quantity": 3, "purchase_price": 100.0, "sale_price": 120.0, "item_discount": 0.0
    }])  # total 300

    # Cash payment in period: 80 (make it CLEARED so cleared-only reporting counts it)
    ppay = PurchasePaymentsRepo(conn)
    ppay.record_payment(
        purchase_id=pid1, amount=80.0, method="Bank Transfer",
        bank_account_id=ids["company_meezan"], vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="online", instrument_no="BT-200",
        instrument_date="2025-01-12", deposited_date=None, cleared_date="2025-01-12",
        clearing_state="cleared", ref_no=None, notes=None, date="2025-01-12", created_by=None
    )

    # Apply credit in period: 50
    vadv.apply_credit_to_purchase(
        vendor_id=ids["vendor_id"], purchase_id=pid1, amount=50.0,
        date="2025-01-15", notes="apply credit", created_by=None
    )

    # Controller: build the statement
    controller = VendorController(conn)  # view exists but we won't show it
    out = controller.build_vendor_statement(
        vendor_id=ids["vendor_id"],
        date_from="2025-01-01", date_to="2025-01-31",
        include_opening=True, show_return_origins=True
    )

    # Shape checks
    assert out["vendor_id"] == ids["vendor_id"]
    assert out["period"]["from"] == "2025-01-01"
    assert out["period"]["to"] == "2025-01-31"
    assert isinstance(out["opening_credit"], float)
    assert isinstance(out["opening_payable"], float)
    assert isinstance(out["rows"], list)
    assert set(out["totals"].keys()) == {"purchases", "cash_paid", "refunds", "credit_notes", "credit_applied"}
    assert isinstance(out["closing_balance"], float)

    # Spot totals (within period)
    # Purchases total should include pid1 only (≈300)
    assert abs(out["totals"]["purchases"] - 300.0) < 1e-6
    # Cash paid: 80
    assert abs(out["totals"]["cash_paid"] - 80.0) < 1e-6
    # Credit applied: 50
    assert abs(out["totals"]["credit_applied"] - 50.0) < 1e-6

    # Opening credit is the grant before the period
    assert abs(out["opening_credit"] - 120.0) < 1e-6
