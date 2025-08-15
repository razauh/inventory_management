# tests/test_reporting_aging.py
import sqlite3
from pathlib import Path
import pytest

from inventory_management.modules.reporting.vendor_aging_reports import VendorAgingReports

from inventory_management.database.repositories.purchases_repo import (
    PurchasesRepo, PurchaseHeader, PurchaseItem
)
from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo
)
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "myshop.db"
SEED_SQL = PROJECT_ROOT / "tests" / "seed_common.sql"

@pytest.fixture(scope="session", autouse=True)
def apply_common_seed():
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("PRAGMA foreign_keys=ON;")
        con.executescript(SEED_SQL.read_text())
        con.commit()
    finally:
        con.close()

@pytest.fixture()
def conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("BEGIN;")
    try:
        yield con
        con.rollback()
    finally:
        con.close()

def _new_purchase_id(con: sqlite3.Connection, date_str: str) -> str:
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

def _build_header(pid: str, vendor_id: int, date: str, *, order_discount=0.0, notes=None, created_by=None):
    return PurchaseHeader(
        purchase_id=pid,
        vendor_id=vendor_id,
        date=date,
        total_amount=0.0,              # repo recalculates
        order_discount=order_discount,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=notes,
        created_by=created_by,
    )

def _ids(conn: sqlite3.Connection):
    def one(sql, *p):
        r = conn.execute(sql, p).fetchone()
        return None if r is None else (r[0] if not isinstance(r, sqlite3.Row) else list(r)[0])
    vendor_id = one("SELECT vendor_id FROM vendors WHERE name='Vendor X' LIMIT 1")
    company_meezan = one("SELECT account_id FROM company_bank_accounts WHERE label='Meezan — Current' LIMIT 1")
    uom_piece = one("SELECT uom_id FROM uoms WHERE unit_name='Piece'")
    prod_A = one("SELECT product_id FROM products WHERE name='Widget A'")
    prod_B = one("SELECT product_id FROM products WHERE name='Widget B'")
    v_primary = conn.execute(
        "SELECT vendor_bank_account_id FROM vendor_bank_accounts WHERE vendor_id=? AND is_primary=1",
        (vendor_id,)
    ).fetchone()
    return {
        "vendor_id": vendor_id,
        "company_meezan": company_meezan,
        "uom_piece": uom_piece,
        "prod_A": prod_A,
        "prod_B": prod_B,
        "vendor_primary_vba": (None if v_primary is None else int(v_primary[0])),
    }

@pytest.mark.skipif(VendorAgingReports is None, reason="Vendor aging reports module missing")
def test_r1_compute_aging_snapshot(conn):
    ids = _ids(conn)
    pr = PurchasesRepo(conn)
    ppay = PurchasePaymentsRepo(conn)
    vadv = VendorAdvancesRepo(conn)

    # Helper to create a simple one-line purchase
    def make_po(date, product_id, qty, buy_price, item_disc=0.0, order_disc=0.0):
        pid = _new_purchase_id(conn, date)
        header = _build_header(pid, ids["vendor_id"], date, order_discount=order_disc, notes=None, created_by=None)
        items = [PurchaseItem(None, pid, product_id, qty, ids["uom_piece"], buy_price, buy_price, item_disc)]
        pr.create_purchase(header, items)
        return pid

    # Create several purchases prior to/as of 2025-01-31 with mixed payment states
    # P1 (0-30 bucket): total 200, paid 50 => remaining 150, date 2025-01-10
    p1 = make_po("2025-01-10", ids["prod_A"], 2, 100.0, 0.0, 0.0)
    ppay.record_payment(
        purchase_id=p1, amount=50.0, method="Bank Transfer",
        bank_account_id=ids["company_meezan"], vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="online", instrument_no="BT-50-P1",
        instrument_date="2025-01-10", deposited_date=None, cleared_date=None,
        clearing_state="posted", ref_no=None, notes=None, date="2025-01-10", created_by=None
    )

    # P2 (0-30 bucket): total 100, unpaid => remaining 100, date 2025-01-25
    p2 = make_po("2025-01-25", ids["prod_A"], 10, 10.0, 0.0, 0.0)

    # P3 (31-60 bucket): total 300, unpaid => remaining 300, date 2024-12-20
    p3 = make_po("2024-12-20", ids["prod_A"], 3, 100.0, 0.0, 0.0)

    # P4 (90+ bucket): total 200, paid 20 => remaining 180, date 2024-10-10
    p4 = make_po("2024-10-10", ids["prod_B"], 4, 50.0, 0.0, 0.0)
    ppay.record_payment(
        purchase_id=p4, amount=20.0, method="Bank Transfer",
        bank_account_id=ids["company_meezan"], vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="online", instrument_no="BT-20-P4",
        instrument_date="2024-10-10", deposited_date=None, cleared_date=None,
        clearing_state="posted", ref_no=None, notes=None, date="2024-10-10", created_by=None
    )

    # P5 (0-30 bucket but fully paid -> excluded): total 200, paid 200
    p5 = make_po("2025-01-01", ids["prod_B"], 1, 200.0, 0.0, 0.0)
    ppay.record_payment(
        purchase_id=p5, amount=200.0, method="Bank Transfer",
        bank_account_id=ids["company_meezan"], vendor_bank_account_id=ids["vendor_primary_vba"],
        instrument_type="online", instrument_no="BT-200-P5",
        instrument_date="2025-01-01", deposited_date=None, cleared_date=None,
        clearing_state="posted", ref_no=None, notes=None, date="2025-01-01", created_by=None
    )

    # Grant vendor credit before cutoff (not applied to invoices)
    vadv.grant_credit(ids["vendor_id"], amount=150.0, date="2025-01-05", notes="credit grant", created_by=None)

    # Sanity: compute expected remaining due from DB up to cutoff
    cutoff = "2025-01-31"
    expected_total_remaining = conn.execute(
        """
        SELECT COALESCE(SUM(
          CAST(p.total_amount AS REAL)
          - CAST(p.paid_amount AS REAL)
          - CAST(p.advance_payment_applied AS REAL)
        ), 0.0) AS remaining
        FROM purchases p
        WHERE p.vendor_id=?
          AND DATE(p.date) <= DATE(?)
          AND (CAST(p.total_amount AS REAL) - CAST(p.paid_amount AS REAL) - CAST(p.advance_payment_applied AS REAL)) > 1e-9
        """,
        (ids["vendor_id"], cutoff)
    ).fetchone()["remaining"]

    # Run report
    rep = VendorAgingReports(conn)
    snapshot = rep.compute_aging_snapshot(cutoff)

    # Find our vendor
    row = next((r for r in snapshot if r["vendor_id"] == ids["vendor_id"]), None)
    assert row is not None

    # 1) Sum of bucket totals equals total_due
    bucket_sum = sum(float(v) for v in row["buckets"].values())
    assert abs(bucket_sum - float(row["total_due"])) < 1e-6

    # 2) Sum across all vendors equals DB remaining due (for our single vendor, this is identical)
    all_bucket_sum = sum(
        sum(float(v) for v in r["buckets"].values())
        for r in snapshot
    )
    assert abs(all_bucket_sum - float(expected_total_remaining)) < 1e-6

    # 3) Credit column matches current vendor credit balance (as-of is earlier than/equal to our entries)
    credit_bal = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)),0.0) AS bal FROM vendor_advances WHERE vendor_id=?",
        (ids["vendor_id"],)
    ).fetchone()["bal"]
    assert "available_credit" in row
    assert abs(float(row["available_credit"]) - float(credit_bal)) < 1e-6

    # 4) Buckets include the standard '0-30' key (basic shape check)
    assert "0-30" in row["buckets"]
