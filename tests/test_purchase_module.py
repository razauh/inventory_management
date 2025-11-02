# tests/test_purchase_module.py
import sqlite3
from pathlib import Path
import pytest

# --- Project imports ---
from inventory_management.database.repositories.purchases_repo import (
    PurchasesRepo, PurchaseHeader, PurchaseItem
)
from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo
)
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo
)

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
    user_ops       = one("SELECT user_id FROM users WHERE username='ops' LIMIT 1")
    return {
        "vendor_id": vendor_id,
        "vendor_primary_vba": (None if v_primary is None else int(v_primary[0])),
        "company_meezan": company_meezan,
        "company_hbl": company_hbl,
        "uom_piece": one("SELECT uom_id FROM uoms WHERE unit_name='Piece'"),
        "uom_box":   one("SELECT uom_id FROM uoms WHERE unit_name='Box'"),
        "prod_A": one("SELECT product_id FROM products WHERE name='Widget A'"),
        "prod_B": one("SELECT product_id FROM products WHERE name='Widget B'"),
        "ops_user": user_ops,
    }


def new_purchase_id(con: sqlite3.Connection, date_str: str) -> str:
    """PO IDs as POYYYYMMDD-#### with daily sequence."""
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


def build_header(pid: str, vendor_id: int, date: str, *, order_discount=0.0, notes=None, created_by=None) -> PurchaseHeader:
    return PurchaseHeader(
        purchase_id=pid,
        vendor_id=vendor_id,
        date=date,
        total_amount=0.0,            # repo recomputes
        order_discount=order_discount,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=notes,
        created_by=created_by,
    )


# ---------------------------------------
# P1 — Create a purchase (no payments)
# ---------------------------------------
def test_p1_create_purchase_no_payments(conn, ids):
    pr = PurchasesRepo(conn)

    date = "2025-01-05"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=50.0, notes="first PO", created_by=ids["ops_user"])
    items = [
        PurchaseItem(None, pid, ids["prod_A"], 10, ids["uom_piece"], 100.0, 120.0, 5.0),
        PurchaseItem(None, pid, ids["prod_B"],  5, ids["uom_piece"], 200.0, 240.0, 0.0),
    ]

    pr.create_purchase(header, items)

    # Header check (exact total)
    row = conn.execute(
        """SELECT purchase_id, vendor_id, date,
                  CAST(total_amount AS REAL) AS total_amount,
                  CAST(order_discount AS REAL) AS order_discount,
                  payment_status,
                  CAST(paid_amount AS REAL) AS paid_amount,
                  CAST(advance_payment_applied AS REAL) AS adv
           FROM purchases WHERE purchase_id=?""",
        (pid,)
    ).fetchone()
    assert row is not None
    assert row["vendor_id"] == ids["vendor_id"]
    assert row["date"] == date
    assert abs(row["total_amount"] - 1900.0) < 1e-6
    assert abs(row["order_discount"] - 50.0) < 1e-6
    assert row["payment_status"] == "unpaid"
    assert abs(row["paid_amount"] - 0.0) < 1e-6
    assert abs(row["adv"] - 0.0) < 1e-6

    # Items present
    rows_items = conn.execute(
        """SELECT product_id, CAST(quantity AS REAL) AS q, uom_id,
                         CAST(purchase_price AS REAL) AS p, CAST(item_discount AS REAL) AS d
           FROM purchase_items WHERE purchase_id=? ORDER BY item_id""",
        (pid,)
    ).fetchall()
    assert len(rows_items) == 2
    assert (rows_items[0]["product_id"], rows_items[0]["q"], rows_items[0]["uom_id"]) == (ids["prod_A"], 10.0, ids["uom_piece"])
    assert (rows_items[1]["product_id"], rows_items[1]["q"], rows_items[1]["uom_id"]) == (ids["prod_B"], 5.0,  ids["uom_piece"])

    # Inventory rows + txn_seq
    rows_inv = conn.execute(
        """SELECT transaction_type, reference_table, reference_id, reference_item_id, date, txn_seq
           FROM inventory_transactions WHERE reference_id=? ORDER BY txn_seq""",
        (pid,)
    ).fetchall()
    assert len(rows_inv) == 2
    assert [r["txn_seq"] for r in rows_inv] == [10, 20]
    assert all(r["transaction_type"] == "purchase" for r in rows_inv)
    assert all(r["reference_table"] == "purchases" for r in rows_inv)

    # View: purchase_detailed_totals
    dtot = conn.execute(
        "SELECT CAST(calculated_total_amount AS REAL) AS calc FROM purchase_detailed_totals WHERE purchase_id=?",
        (pid,)
    ).fetchone()
    assert dtot is not None and abs(dtot["calc"] - 1900.0) < 1e-6

    # Valuation & on-hand (moving-average)
    soh = conn.execute(
        "SELECT product_id, CAST(qty_in_base AS REAL) AS q, CAST(unit_value AS REAL) AS uc FROM v_stock_on_hand WHERE product_id IN (?,?)",
        (ids["prod_A"], ids["prod_B"])
    ).fetchall()
    # Build a dict for easy lookup
    soh_map = {r["product_id"]: (r["q"], r["uc"]) for r in soh}
    assert ids["prod_A"] in soh_map and ids["prod_B"] in soh_map
    qa, uca = soh_map[ids["prod_A"]]
    qb, ucb = soh_map[ids["prod_B"]]
    assert abs(qa - 10.0) < 1e-6 and abs(uca - 95.0) < 1e-6  # 100-5
    assert abs(qb -  5.0) < 1e-6 and abs(ucb - 200.0) < 1e-6


# -------------------------------------------------------------
# P2 — Create purchase with initial cash payment (cleared)
# -------------------------------------------------------------
def test_p2_purchase_with_initial_payment(conn, ids):
    pr   = PurchasesRepo(conn)
    payr = PurchasePaymentsRepo(conn)

    date = "2025-01-06"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=0.0, notes=None, created_by=ids["ops_user"])
    items = [PurchaseItem(None, pid, ids["prod_A"], 2, ids["uom_piece"], 100.0, 120.0, 0.0)]
    pr.create_purchase(header, items)

    # Pay full amount via Bank Transfer (cleared)
    payr.record_payment(
        purchase_id=pid,
        amount=200.0,
        method="Bank Transfer",
        bank_account_id=ids["company_meezan"],
        vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="online",
        instrument_no="TRX-123",
        instrument_date=date,
        deposited_date=None,
        cleared_date=None,
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date=date,
        created_by=ids["ops_user"],
    )

    # Header rolled-up
    hdr = conn.execute("SELECT CAST(paid_amount AS REAL) AS p, payment_status FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
    assert abs(hdr["p"] - 200.0) < 1e-6
    assert hdr["payment_status"] == "paid"

    # Payment row fields
    prow = conn.execute(
        """SELECT CAST(amount AS REAL) AS a, method, bank_account_id, vendor_bank_account_id,
                  instrument_type, instrument_no, clearing_state
           FROM purchase_payments WHERE purchase_id=?""",
        (pid,)
    ).fetchone()
    assert prow is not None
    assert abs(prow["a"] - 200.0) < 1e-6
    assert prow["method"] == "Bank Transfer"
    assert prow["bank_account_id"] == ids["company_meezan"]
    assert prow["vendor_bank_account_id"] == ids["vendor_primary_vba"]
    assert prow["instrument_type"] == "online"
    assert prow["instrument_no"] == "TRX-123"
    assert prow["clearing_state"] == "cleared"

    # Bank ledger should show amount_out=200
    bl = conn.execute(
        "SELECT CAST(amount_out AS REAL) AS outv FROM v_bank_ledger_ext WHERE src='purchase' AND doc_id=?",
        (pid,)
    ).fetchall()
    assert any(abs(r["outv"] - 200.0) < 1e-6 for r in bl)


# ---------------------------------------------------------
# P3 — Record cheque payment, then clear it
# ---------------------------------------------------------
def test_p3_cheque_payment_then_clear(conn, ids):
    pr   = PurchasesRepo(conn)
    payr = PurchasePaymentsRepo(conn)

    # Recreate P1-like purchase (1900 total)
    date = "2025-01-05"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=50.0, notes="first PO", created_by=ids["ops_user"])
    items = [
        PurchaseItem(None, pid, ids["prod_A"], 10, ids["uom_piece"], 100.0, 120.0, 5.0),
        PurchaseItem(None, pid, ids["prod_B"],  5, ids["uom_piece"], 200.0, 240.0, 0.0),
    ]
    pr.create_purchase(header, items)

    # Cheque payment (pending)
    payment_id = payr.record_payment(
        purchase_id=pid,
        amount=1000.0,
        method="Cheque",
        bank_account_id=ids["company_hbl"],
        vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="cross_cheque",
        instrument_no="CHQ-555",
        instrument_date="2025-01-07",
        deposited_date=None,
        cleared_date=None,
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2025-01-07",
        created_by=ids["ops_user"],
    )

    # With new behavior, all payments are cleared by default, so the cheque immediately reduces payable
    hdr = conn.execute(
        "SELECT CAST(paid_amount AS REAL) AS p, payment_status FROM purchases WHERE purchase_id=?",
        (pid,)
    ).fetchone()
    assert abs(hdr["p"] - 1000.0) < 1e-6
    assert hdr["payment_status"] == "partial"

    # The payment is already cleared, so this is just for testing purposes
    # Clear the cheque again (should still be cleared)
    affected = payr.update_clearing_state(payment_id, clearing_state="cleared", cleared_date="2025-01-10")
    assert affected == 1
    prw = conn.execute("SELECT clearing_state, cleared_date FROM purchase_payments WHERE payment_id=?", (payment_id,)).fetchone()
    assert prw["clearing_state"] == "cleared"
    assert prw["cleared_date"] == "2025-01-10"

    # It should still be partial since it was already partial
    hdr2 = conn.execute(
        "SELECT CAST(paid_amount AS REAL) AS p, payment_status FROM purchases WHERE purchase_id=?",
        (pid,)
    ).fetchone()
    assert abs(hdr2["p"] - 1000.0) < 1e-6
    assert hdr2["payment_status"] == "partial"


# -----------------------------------------------------------------
# P4 — Record purchase return with refund now (cash incoming)
# -----------------------------------------------------------------
def test_p4_return_with_refund_now(conn, ids):
    pr   = PurchasesRepo(conn)
    payr = PurchasePaymentsRepo(conn)

    # Base purchase (P1 pattern)
    date = "2025-01-05"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=50.0, notes="first PO", created_by=ids["ops_user"])
    items = [
        PurchaseItem(None, pid, ids["prod_A"], 10, ids["uom_piece"], 100.0, 120.0, 5.0),
        PurchaseItem(None, pid, ids["prod_B"],  5, ids["uom_piece"], 200.0, 240.0, 0.0),
    ]
    pr.create_purchase(header, items)

    # Return 3 of Widget A, refund now
    # Need the item_id for Widget A line
    a_item_id = conn.execute(
        "SELECT item_id FROM purchase_items WHERE purchase_id=? AND product_id=? LIMIT 1",
        (pid, ids["prod_A"])
    ).fetchone()["item_id"]

    pr.record_return(
        pid=pid,
        date="2025-01-08",
        created_by=ids["ops_user"],
        notes="return A",
        lines=[{"item_id": a_item_id, "qty_return": 3.0}],
        settlement={
            "mode": "refund",
            "method": "Bank Transfer",
            "bank_account_id": ids["company_meezan"],
            # For negative amount, vendor_bank_account_id may be NULL; pass None to satisfy trigger relax
            "vendor_bank_account_id": None,
            "instrument_type": "online",
            "instrument_no": "RN-TRX-1",
        },
    )

    # Return valuation should be 285
    val = conn.execute(
        "SELECT CAST(return_value AS REAL) AS v FROM purchase_return_valuations WHERE purchase_id=? ORDER BY transaction_id DESC LIMIT 1",
        (pid,)
    ).fetchone()
    assert val is not None and abs(val["v"] - 285.0) < 1e-6

    # Payments should include a negative (incoming) 285
    refunds_in = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN amount<0 THEN -CAST(amount AS REAL) ELSE 0 END),0.0) AS refunds_in FROM purchase_payments WHERE purchase_id=?",
        (pid,)
    ).fetchone()
    assert abs(refunds_in["refunds_in"] - 285.0) < 1e-6

    # Header clamp keeps paid_amount >= 0 (no positive payments yet)
    hdr = conn.execute("SELECT CAST(paid_amount AS REAL) AS p, payment_status FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
    assert abs(hdr["p"] - 0.0) < 1e-6
    assert hdr["payment_status"] == "unpaid"

    # Stock on hand for A should be 7 now (10 - 3)
    sohA = conn.execute(
        "SELECT CAST(qty_in_base AS REAL) AS q FROM v_stock_on_hand WHERE product_id=?",
        (ids["prod_A"],)
    ).fetchone()
    assert sohA is not None and abs(sohA["q"] - 7.0) < 1e-6

    # Bank ledger incoming = 285
    bl = conn.execute(
        "SELECT CAST(amount_in AS REAL) AS inv FROM v_bank_ledger_ext WHERE src='purchase' AND doc_id=? ORDER BY payment_id DESC LIMIT 1",
        (pid,)
    ).fetchone()
    assert bl is not None and abs(bl["inv"] - 285.0) < 1e-6


# ----------------------------------------------------
# P5 — Record purchase return with credit note
# ----------------------------------------------------
def test_p5_return_with_credit_note(conn, ids):
    pr  = PurchasesRepo(conn)
    vad = VendorAdvancesRepo(conn)

    # Base purchase (P1 pattern)
    date = "2025-01-05"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=50.0, notes="first PO", created_by=ids["ops_user"])
    items = [
        PurchaseItem(None, pid, ids["prod_A"], 10, ids["uom_piece"], 100.0, 120.0, 5.0),
        PurchaseItem(None, pid, ids["prod_B"],  5, ids["uom_piece"], 200.0, 240.0, 0.0),
    ]
    pr.create_purchase(header, items)

    # Return 1 of Widget B as credit note on 2025-01-08
    b_item_id = conn.execute(
        "SELECT item_id FROM purchase_items WHERE purchase_id=? AND product_id=? LIMIT 1",
        (pid, ids["prod_B"])
    ).fetchone()["item_id"]

    pr.record_return(
        pid=pid,
        date="2025-01-08",
        created_by=ids["ops_user"],
        notes="credit note",
        lines=[{"item_id": b_item_id, "qty_return": 1.0}],
        settlement={"mode": "credit_note"},
    )

    # Vendor advances increased by +200
    sum_adv = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)),0.0) AS s FROM vendor_advances WHERE vendor_id=?",
        (ids["vendor_id"],)
    ).fetchone()
    assert abs(sum_adv["s"] - 200.0) < 1e-6

    bal = conn.execute(
        "SELECT CAST(balance AS REAL) AS b FROM v_vendor_advance_balance WHERE vendor_id=?",
        (ids["vendor_id"],)
    ).fetchone()
    assert bal is not None and abs(bal["b"] - 200.0) < 1e-6

    # No purchase payment rows were added by this credit-note action
    cnt = conn.execute(
        "SELECT COUNT(*) AS c FROM purchase_payments WHERE purchase_id=? AND date='2025-01-08'",
        (pid,)
    ).fetchone()
    assert int(cnt["c"]) == 0


# ----------------------------------------------------------
# P6 — Apply vendor credit to a purchase
# ----------------------------------------------------------
def test_p6_apply_vendor_credit(conn, ids):
    pr  = PurchasesRepo(conn)
    vad = VendorAdvancesRepo(conn)

    # Base purchase (P1 pattern)
    date = "2025-01-05"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=50.0, notes="first PO", created_by=ids["ops_user"])
    items = [
        PurchaseItem(None, pid, ids["prod_A"], 10, ids["uom_piece"], 100.0, 120.0, 5.0),
        PurchaseItem(None, pid, ids["prod_B"],  5, ids["uom_piece"], 200.0, 240.0, 0.0),
    ]
    pr.create_purchase(header, items)

    # Have credit 200, then apply 200 to this purchase
    vad.grant_credit(ids["vendor_id"], 200.0, date="2025-01-08", notes="grant", created_by=ids["ops_user"])
    vad.apply_credit_to_purchase(ids["vendor_id"], pid, 200.0, date="2025-01-09", notes="apply", created_by=ids["ops_user"])

    hdr = conn.execute(
        "SELECT CAST(advance_payment_applied AS REAL) AS a FROM purchases WHERE purchase_id=?",
        (pid,)
    ).fetchone()
    assert abs(hdr["a"] - 200.0) < 1e-6

    # Balance back to 0
    bal = conn.execute(
        "SELECT CAST(balance AS REAL) AS b FROM v_vendor_advance_balance WHERE vendor_id=?",
        (ids["vendor_id"],)
    ).fetchone()
    assert bal is not None and abs(bal["b"] - 0.0) < 1e-6

    # Sum of -amount for this purchase equals advance_payment_applied
    srow = conn.execute(
        """SELECT COALESCE(SUM(-CAST(amount AS REAL)),0.0) AS applied_to_po
           FROM vendor_advances
           WHERE source_type='applied_to_purchase' AND source_id=?""",
        (pid,)
    ).fetchone()
    assert abs(srow["applied_to_po"] - 200.0) < 1e-6


# -------------------------------------------
# P7 — Over-return must fail (guard)
# -------------------------------------------
def test_p7_over_return_fails(conn, ids):
    pr = PurchasesRepo(conn)

    date = "2025-01-05"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=0.0, notes=None, created_by=ids["ops_user"])
    items = [PurchaseItem(None, pid, ids["prod_A"], 5, ids["uom_piece"], 100.0, 120.0, 0.0)]
    pr.create_purchase(header, items)

    # Try to return more than purchased
    a_item_id = conn.execute(
        "SELECT item_id FROM purchase_items WHERE purchase_id=? AND product_id=? LIMIT 1",
        (pid, ids["prod_A"])
    ).fetchone()["item_id"]

    with pytest.raises(ValueError):
        pr.record_return(
            pid=pid,
            date="2025-01-10",
            created_by=ids["ops_user"],
            notes="over",
            lines=[{"item_id": a_item_id, "qty_return": 999.0}],
            settlement=None,
        )

    # No purchase_return rows were created for that date
    n = conn.execute(
        """SELECT COUNT(*) AS c
           FROM inventory_transactions
           WHERE reference_table='purchases' AND reference_id=?
             AND transaction_type='purchase_return' AND date=DATE('2025-01-10')""",
        (pid,)
    ).fetchone()
    assert int(n["c"]) == 0


# ----------------------------------------------------------------------
# P8 — UoM enforcement: non-base UoM must fail for purchase lines
# ----------------------------------------------------------------------
def test_p8_non_base_uom_rejected(conn, ids):
    pr = PurchasesRepo(conn)

    date = "2025-01-11"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=0.0, notes=None, created_by=ids["ops_user"])
    # Widget A 'Box' is non-base per seed (base is 'Piece')
    items = [PurchaseItem(None, pid, ids["prod_A"], 1, ids["uom_box"], 1000.0, 1200.0, 0.0)]

    # Use a SAVEPOINT so we can roll back only this attempted insert
    conn.execute("SAVEPOINT p8;")
    with pytest.raises(sqlite3.IntegrityError) as ei:
        pr.create_purchase(header, items)
    assert "Purchases must use the product base UoM" in str(ei.value)
    # Roll back just the failed insert and keep the outer test transaction active
    conn.execute("ROLLBACK TO SAVEPOINT p8;")
    conn.execute("RELEASE SAVEPOINT p8;")

    # Check no rows exist for this purchase id
    c_items = conn.execute("SELECT COUNT(*) AS c FROM purchase_items WHERE purchase_id=?", (pid,)).fetchone()
    c_itx   = conn.execute("SELECT COUNT(*) AS c FROM inventory_transactions WHERE reference_id=?", (pid,)).fetchone()
    c_hdr   = conn.execute("SELECT COUNT(*) AS c FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
    assert int(c_items["c"]) == 0
    assert int(c_itx["c"]) == 0
    assert int(c_hdr["c"]) == 0

# -------------------------------------------------------------------------
# P9 — Edit purchase: only purchase inventory rebuilt; returns remain
# -------------------------------------------------------------------------
def test_p9_update_purchase_keeps_returns(conn, ids):
    pr = PurchasesRepo(conn)

    date = "2025-01-05"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=50.0, notes="first PO", created_by=ids["ops_user"])
    items = [
        PurchaseItem(None, pid, ids["prod_A"], 10, ids["uom_piece"], 100.0, 120.0, 5.0),
        PurchaseItem(None, pid, ids["prod_B"],  5, ids["uom_piece"], 200.0, 240.0, 0.0),
    ]
    pr.create_purchase(header, items)

    # Create a return first (so it should remain)
    a_item_id = conn.execute(
        "SELECT item_id FROM purchase_items WHERE purchase_id=? AND product_id=? LIMIT 1",
        (pid, ids["prod_A"])
    ).fetchone()["item_id"]
    pr.record_return(
        pid=pid,
        date="2025-01-08",
        created_by=ids["ops_user"],
        notes="pre-update return",
        lines=[{"item_id": a_item_id, "qty_return": 1.0}],
        settlement=None,
    )

    # Now edit purchase: change A qty 10 -> 8 (keep the rest)
    header2 = build_header(pid, ids["vendor_id"], date, order_discount=50.0, notes="edited", created_by=ids["ops_user"])
    new_items = [
        PurchaseItem(None, pid, ids["prod_A"], 8, ids["uom_piece"], 100.0, 120.0, 5.0),
        PurchaseItem(None, pid, ids["prod_B"], 5, ids["uom_piece"], 200.0, 240.0, 0.0),
    ]
    pr.update_purchase(header2, new_items)

    # Purchase inventory rows re-created (txn_seq 10,20) but returns still exist
    rows = conn.execute(
        """SELECT transaction_id, transaction_type, txn_seq
           FROM inventory_transactions WHERE reference_id=?
           ORDER BY transaction_id""",
        (pid,)
    ).fetchall()
    have_returns = [r for r in rows if r["transaction_type"] == "purchase_return"]
    have_purch   = [r for r in rows if r["transaction_type"] == "purchase"]
    assert len(have_returns) >= 1
    assert [r["txn_seq"] for r in have_purch] == [10, 20]

    # Header total updated: 8*(100-5) + 5*200 - 50 = 1710
    hdr = conn.execute("SELECT CAST(total_amount AS REAL) AS t FROM purchases WHERE purchase_id=?", (pid,)).fetchone()
    assert abs(hdr["t"] - 1710.0) < 1e-6


# -------------------------------------------------------------------
# P10 — Back-dated insertion marks valuation_dirty (sanity)
# -------------------------------------------------------------------
def test_p10_backdated_marks_dirty(conn, ids):
    pr = PurchasesRepo(conn)

    # First create a later valuation snapshot (2025-01-20)
    pid1 = new_purchase_id(conn, "2025-01-20")
    header1 = build_header(pid1, ids["vendor_id"], "2025-01-20", notes=None, created_by=ids["ops_user"])
    items1 = [PurchaseItem(None, pid1, ids["prod_A"], 1, ids["uom_piece"], 90.0, 100.0, 0.0)]
    pr.create_purchase(header1, items1)

    # Now insert a back-dated purchase for the same product (2025-01-10)
    pid2 = new_purchase_id(conn, "2025-01-10")
    header2 = build_header(pid2, ids["vendor_id"], "2025-01-10", notes=None, created_by=ids["ops_user"])
    items2 = [PurchaseItem(None, pid2, ids["prod_A"], 1, ids["uom_piece"], 80.0, 100.0, 0.0)]
    pr.create_purchase(header2, items2)

    # valuation_dirty should be marked for product A
    vrow = conn.execute(
        "SELECT product_id, earliest_impacted FROM valuation_dirty WHERE product_id=?",
        (ids["prod_A"],)
    ).fetchone()
    assert vrow is not None
    # earliest_impacted should be <= the back-dated date
    assert vrow["earliest_impacted"] <= "2025-01-10"


# -------------------------------------------------------------------
# P11 — Over-apply credit beyond remaining due must fail (new guard)
# -------------------------------------------------------------------
def test_p11_overapply_credit_beyond_due_fails(conn, ids):
    pr = PurchasesRepo(conn)
    vadv = VendorAdvancesRepo(conn)

    # Create a small purchase with remaining due = 100
    date = "2025-02-01"
    pid = new_purchase_id(conn, date)
    header = build_header(pid, ids["vendor_id"], date, order_discount=0.0, notes=None, created_by=ids["ops_user"])
    items = [PurchaseItem(None, pid, ids["prod_A"], 1, ids["uom_piece"], 100.0, 120.0, 0.0)]
    pr.create_purchase(header, items)

    # Grant ample vendor credit
    vadv.grant_credit(ids["vendor_id"], amount=500.0, date="2025-02-01", notes="bulk deposit", created_by=ids["ops_user"])

    # Attempt to apply 200 credit to a purchase that only has 100 due -> should fail
    with pytest.raises(sqlite3.IntegrityError):
        vadv.apply_credit_to_purchase(
            vendor_id=ids["vendor_id"],
            purchase_id=pid,
            amount=200.0,
            date="2025-02-02",
            notes="over-apply",
            created_by=ids["ops_user"],
        )

    # Confirm no change to the purchase header’s advance_payment_applied
    hdr = conn.execute(
        "SELECT CAST(advance_payment_applied AS REAL) AS a FROM purchases WHERE purchase_id=?",
        (pid,)
    ).fetchone()
    assert abs(hdr["a"] - 0.0) < 1e-6
