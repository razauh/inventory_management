#!/usr/bin/env python3
"""
Seed script for the inventory_management project.

What it does now:
- Uses the existing DB file & schema (does NOT create or init schema).
- Wipes data rows (with FK off) and reseeds:
  * Company "Al Husnain Solar Energy"
  * Company bank accounts: "Meezan — Current", "Allied Bank — Current"
  * User: ops (admin)
  * UoMs: Piece (base), Box (alt)
  * Vendors: N (with 1 primary bank account; ~40% also get a second)
  * Products: M (all base=Piece; ~35% also 'Box' factor 10)
  * Purchases: K with varied line counts/prices
  * Payments: Bank Transfer / Cheque / Cash Deposit / Cash
    - clearing_state: cleared, pending→cleared, pending→bounced, posted
  * Returns: credit_note and refund/refund_now (incoming BT)
  * Vendor credits: deposits + occasional applications
  * Back-dated POs to mark valuation_dirty.

Usage:
  python -m inventory_management.database.seeders.bulk_seed \
    --db inventory_management/data/myshop.db \
    --pos 1000 --vendors 10 --products 100 --seed 20250101

IMPORTANT: Run your schema initializer first so tables & triggers exist.
"""

import argparse
import random
import string
import sqlite3
from pathlib import Path
from datetime import date, timedelta

# --- project repositories ---
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
from inventory_management.database.repositories.products_repo import (
    ProductsRepo
)
from inventory_management.database.repositories.vendors_repo import (
    VendorsRepo
)

# ----------------------------
# Helpers / deterministic RNG
# ----------------------------

def rnd_label(rng: random.Random, prefix: str, n=6) -> str:
    return f"{prefix}-{''.join(rng.choices(string.ascii_uppercase + string.digits, k=n))}"

def new_purchase_id(con: sqlite3.Connection, date_str: str) -> str:
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

def dtstr(d: date) -> str:
    return d.isoformat()

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

# ----------------------------
# Data wipe (keep schema)
# ----------------------------

def reset_db(con: sqlite3.Connection):
    con.execute("PRAGMA foreign_keys=OFF;")
    cur = con.cursor()
    tables = [
        "purchase_payments",
        "inventory_transactions",
        "purchase_items",
        "purchases",
        "purchase_returns",
        "vendor_advances",
        "vendor_bank_accounts",
        "vendors",
        "product_uoms",
        "products",
        "uoms",
        "company_bank_accounts",
        "company_info",
        "users",
        "valuation_dirty",
    ]
    for t in tables:
        try:
            cur.execute(f"DELETE FROM {t};")
        except Exception:
            # ignore if table missing in your build
            pass
    con.commit()
    con.execute("PRAGMA foreign_keys=ON;")

# ----------------------------
# Seed masters
# ----------------------------

def seed_company_and_users(con: sqlite3.Connection):
    con.execute("PRAGMA foreign_keys=ON;")
    con.execute("""
        INSERT INTO company_info(company_id, company_name, address)
        VALUES (1, 'Al Husnain Solar Energy', 'N/A')
        ON CONFLICT(company_id) DO UPDATE SET
          company_name=excluded.company_name, address=excluded.address;
    """)
    con.execute("""
        INSERT INTO company_bank_accounts(company_id, label, bank_name, account_no, is_active)
        VALUES
          (1, 'Meezan — Current', 'Meezan', 'AHS-001', 1)
        ON CONFLICT(company_id, label) DO UPDATE SET
          bank_name=excluded.bank_name, account_no=excluded.account_no, is_active=excluded.is_active;
    """)
    con.execute("""
        INSERT INTO company_bank_accounts(company_id, label, bank_name, account_no, is_active)
        VALUES
          (1, 'Allied Bank — Current', 'Allied Bank', 'AHS-002', 1)
        ON CONFLICT(company_id, label) DO UPDATE SET
          bank_name=excluded.bank_name, account_no=excluded.account_no, is_active=excluded.is_active;
    """)
    con.execute("""
        INSERT INTO users(username, password_hash, full_name, role, is_active)
        VALUES ('ops', 'x', 'Op User', 'admin', 1)
        ON CONFLICT(username) DO UPDATE SET
          password_hash=excluded.password_hash,
          full_name=excluded.full_name,
          role=excluded.role,
          is_active=excluded.is_active;
    """)
    con.commit()

def seed_uoms(con: sqlite3.Connection):
    con.execute("INSERT INTO uoms(unit_name) VALUES ('Piece') ON CONFLICT(unit_name) DO NOTHING;")
    con.execute("INSERT INTO uoms(unit_name) VALUES ('Box')   ON CONFLICT(unit_name) DO NOTHING;")
    con.commit()

def fetch_ids(con: sqlite3.Connection):
    con.row_factory = sqlite3.Row
    one = lambda sql, *p: con.execute(sql, p).fetchone()
    ids = {}
    ids["company_meezan"] = one("SELECT account_id FROM company_bank_accounts WHERE company_id=1 AND label='Meezan — Current'")["account_id"]
    ids["company_allied"] = one("SELECT account_id FROM company_bank_accounts WHERE company_id=1 AND label='Allied Bank — Current'")["account_id"]
    ids["uom_piece"] = one("SELECT uom_id FROM uoms WHERE unit_name='Piece'")["uom_id"]
    ids["uom_box"]   = one("SELECT uom_id FROM uoms WHERE unit_name='Box'")["uom_id"]
    ids["ops_user"]  = one("SELECT user_id FROM users WHERE username='ops'")["user_id"]
    return ids

# ----------------------------
# Vendors & Products
# ----------------------------

def seed_vendors(con: sqlite3.Connection, n_vendors: int, rng: random.Random):
    vbarepo = VendorBankAccountsRepo(con)
    vendor_ids = []
    for i in range(1, n_vendors + 1):
        name = f"Vendor {i:03d}"
        row = con.execute("SELECT vendor_id FROM vendors WHERE name=?;", (name,)).fetchone()
        if row:
            vid = int(row["vendor_id"])
        else:
            email = f"{name.lower().replace(' ','')}@example.test"
            cur = con.execute(
                "INSERT INTO vendors(name, contact_info, address) VALUES (?, ?, ?)",
                (name, email, "N/A"),
            )
            vid = int(cur.lastrowid)
        vendor_ids.append(vid)

        label1 = f"{name} — Meezan"
        try:
            vbarepo.create(vid, {
                "label": label1,
                "bank_name": "Meezan",
                "account_no": f"V{vid:04d}-MZN",
                "iban": None,
                "routing_no": None,
                "is_primary": 1,
                "is_active": 1,
            })
        except sqlite3.IntegrityError:
            con.execute("""
                UPDATE vendor_bank_accounts
                   SET is_primary=1, is_active=1
                 WHERE vendor_id=? AND label=?;
            """, (vid, label1))

        if rng.random() < 0.4:
            label2 = f"{name} — Allied"
            try:
                vbarepo.create(vid, {
                    "label": label2,
                    "bank_name": "Allied Bank",
                    "account_no": f"V{vid:04d}-ALD",
                    "iban": None,
                    "routing_no": None,
                    "is_primary": 0,
                    "is_active": 1,
                })
            except sqlite3.IntegrityError:
                pass

    con.commit()
    return vendor_ids

def seed_products(con: sqlite3.Connection, n_products: int, rng: random.Random, piece_id: int, box_id: int):
    for i in range(1, n_products + 1):
        name = f"Product {i:04d}"
        cur = con.execute(
            "INSERT INTO products(name, description, min_stock_level) VALUES (?, ?, ?) ",
            (name, f"Desc {i:04d}", 0)
        )
        pid = int(cur.lastrowid)
        con.execute("""
            INSERT INTO product_uoms(product_id, uom_id, is_base, factor_to_base)
            VALUES (?, ?, 1, 1.0)
        """, (pid, piece_id))
        if rng.random() < 0.35:
            con.execute("""
                INSERT INTO product_uoms(product_id, uom_id, is_base, factor_to_base)
                VALUES (?, ?, 0, 10.0)
            """, (pid, box_id))
    con.commit()

def list_products(con: sqlite3.Connection):
    return [int(r["product_id"]) for r in con.execute("SELECT product_id FROM products ORDER BY product_id").fetchall()]

def vendor_primary_vba(con: sqlite3.Connection, vendor_id: int) -> int:
    r = con.execute("""
        SELECT vendor_bank_account_id
          FROM vendor_bank_accounts
         WHERE vendor_id=? AND COALESCE(CAST(is_primary AS INTEGER),0)=1
         LIMIT 1
    """, (vendor_id,)).fetchone()
    assert r, f"No primary bank account for vendor {vendor_id}"
    return int(r["vendor_bank_account_id"])

# ----------------------------
# Purchase + payments/returns
# ----------------------------

def create_purchase(con, pr: PurchasesRepo, vendor_id: int, when: date, items_spec, notes=None, created_by=None) -> str:
    pid = new_purchase_id(con, dtstr(when))
    header = PurchaseHeader(
        purchase_id=pid,
        vendor_id=vendor_id,
        date=dtstr(when),
        total_amount=0.0,
        order_discount=0.0,
        payment_status="unpaid",
        paid_amount=0.0,
        advance_payment_applied=0.0,
        notes=notes,
        created_by=created_by,
    )
    items = [PurchaseItem(
        item_id=None,
        purchase_id=pid,
        product_id=it["product_id"],
        quantity=float(it["qty"]),
        uom_id=int(it["uom_id"]),          # base only
        purchase_price=float(it["buy"]),
        sale_price=float(it["sale"]),
        item_discount=float(it["disc"])
    ) for it in items_spec]
    pr.create_purchase(header, items)
    return pid

def po_total(con, purchase_id: str) -> float:
    r = con.execute("SELECT CAST(total_amount AS REAL) AS t FROM purchases WHERE purchase_id=?", (purchase_id,)).fetchone()
    return float(r["t"] or 0.0)

def po_paid_and_due(con, purchase_id: str):
    r = con.execute("""
        SELECT CAST(total_amount AS REAL) AS t, CAST(paid_amount AS REAL) AS p, CAST(advance_payment_applied AS REAL) AS a
          FROM purchases WHERE purchase_id=?""", (purchase_id,)).fetchone()
    total = float(r["t"] or 0.0)
    paid  = float(r["p"] or 0.0)
    adv   = float(r["a"] or 0.0)
    return paid, max(0.0, total - paid - adv)

def list_items(con, purchase_id: str):
    return con.execute("""
        SELECT item_id, product_id, uom_id, CAST(quantity AS REAL) AS qty,
               CAST(purchase_price AS REAL) AS buy, CAST(item_discount AS REAL) AS disc
          FROM purchase_items
         WHERE purchase_id=? ORDER BY item_id
    """, (purchase_id,)).fetchall()

# ----------------------------
# Scenario assignment
# ----------------------------

def assign_payment_scenario(ix: int, n_total: int, rng: random.Random):
    """
    Include Cash scenarios and keep coverage across others.
    """
    buckets = [
        ("none",               0.15),
        ("bt_full_cleared",    0.20),
        ("bt_partial_cleared", 0.12),
        ("chq_pending",        0.07),
        ("chq_clear_later",    0.10),
        ("dep_clear_later",    0.08),
        ("dep_bounced",        0.04),
        ("late_bt_cleared",    0.09),
        ("cash_full_posted",   0.08),  # Cash (posted)
        ("cash_partial_posted",0.07),
    ]
    if ix < 160:
        cycle = [
            "bt_full_cleared", "bt_partial_cleared",
            "chq_clear_later", "dep_clear_later", "dep_bounced",
            "late_bt_cleared",
            "cash_full_posted", "cash_partial_posted",
            "chq_pending",
        ]
        return cycle[ix % len(cycle)]
    x = rng.random()
    acc = 0.0
    for name, w in buckets:
        acc += w
        if x <= acc:
            return name
    return "none"

def forced_return_mode(ix: int):
    return "credit_note" if (ix % 2 == 0) else "refund_now"

def maybe_return_scenario(ix: int, rng: random.Random):
    if ix < 150:
        return forced_return_mode(ix)
    if rng.random() < 0.17:
        return rng.choice(["credit_note", "refund_now"])
    return None

def should_grant_credit_for_vendor(rng: random.Random):
    return rng.random() < 0.60

# ----------------------------
# Summary helpers
# ----------------------------

def count_returns(con: sqlite3.Connection) -> int:
    r = con.execute("""
        SELECT COUNT(*) AS c
          FROM inventory_transactions
         WHERE transaction_type='purchase_return'
    """).fetchone()
    return int(r["c"] or 0)

def payments_summary(con: sqlite3.Connection):
    return con.execute("""
        SELECT method, COALESCE(clearing_state,'') AS clearing_state,
               COUNT(*) AS n,
               ROUND(SUM(CASE WHEN amount>0 THEN amount ELSE 0 END), 2) AS outgoing_total,
               ROUND(SUM(CASE WHEN amount<0 THEN -amount ELSE 0 END), 2) AS incoming_total
          FROM purchase_payments
         GROUP BY method, COALESCE(clearing_state,'')
         ORDER BY method, clearing_state
    """).fetchall()

# ----------------------------
# Main seeding flow
# ----------------------------

def seed_everything(db_path: str, n_pos: int, n_vendors: int, n_products: int, rng_seed: int):
    rng = random.Random(rng_seed)

    # Connect to existing DB (assumes schema already exists)
    print("Connecting to existing DB (no schema init)…")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON;")

    try:
        print("Wiping existing data (keeping schema)…")
        reset_db(con)

        print("Seeding company & users…")
        seed_company_and_users(con)
        print("Seeding UoMs…")
        seed_uoms(con)
        ids = fetch_ids(con)

        print(f"Seeding {n_vendors} vendors…")
        vendor_ids = seed_vendors(con, n_vendors, rng)
        print(f"Seeding {n_products} products…")
        seed_products(con, n_products, rng, ids["uom_piece"], ids["uom_box"])
        product_ids = list_products(con)

        vadv = VendorAdvancesRepo(con)
        print("Granting vendor credits (deposits)…")
        base_start = date.today() - timedelta(days=365)
        for vid in vendor_ids:
            if should_grant_credit_for_vendor(rng):
                for _ in range(rng.randint(2, 6)):
                    when = base_start + timedelta(days=rng.randint(0, 330))
                    amt = rng.choice([100.0, 150.0, 200.0, 250.0, 300.0])
                    vadv.grant_credit(vendor_id=vid, amount=amt, date=dtstr(when), notes="seed grant", created_by=ids["ops_user"])

        pr   = PurchasesRepo(con)
        ppay = PurchasePaymentsRepo(con)

        print(f"Creating {n_pos} purchases with payments/returns…")
        for i in range(n_pos):
            vid = rng.choice(vendor_ids)
            when = base_start + timedelta(days=rng.randint(0, 360))
            n_lines = rng.randint(1, 5)
            items_spec = []
            for _ in range(n_lines):
                pid = rng.choice(product_ids)
                qty = rng.randint(1, 50)
                buy = float(rng.choice([50, 60, 75, 80, 100, 120, 150, 180, 200, 250]))
                disc = float(rng.uniform(0.0, max(0.0, buy - 0.01)))
                sale = float(clamp(buy + rng.uniform(-0.25*buy, 0.3*buy), 1.0, 99999.0))
                items_spec.append({
                    "product_id": pid,
                    "qty": qty,
                    "uom_id": ids["uom_piece"],
                    "buy": buy,
                    "sale": sale,
                    "disc": disc,
                })

            pid = create_purchase(con, pr, vid, when, items_spec, notes=None, created_by=ids["ops_user"])
            total = po_total(con, pid)

            scen = assign_payment_scenario(i, n_pos, rng)
            vba_id = vendor_primary_vba(con, vid)
            comp_acct_out = rng.choice([ids["company_meezan"], ids["company_allied"]])

            def record_payment(amount: float, method: str, state: str, dt: date,
                               vendor_acct_required=True, instrument_type=None, ref_prefix=""):
                if amount < 0.01:
                    return None
                # Cash: leave instrument_type NULL to satisfy the CHECK (unless you added 'cash' to it)
                itype = (None if method == "Cash"
                         else instrument_type or (
                            "online" if method == "Bank Transfer" else
                            "cross_cheque" if method == "Cheque" else
                            "cash_deposit"
                         ))
                return ppay.record_payment(
                    purchase_id=pid,
                    amount=amount,
                    method=method,
                    bank_account_id=(None if method in ("Cash Deposit", "Cash") else comp_acct_out),
                    vendor_bank_account_id=(vba_id if (amount > 0 and vendor_acct_required and method != "Cash") else None),
                    instrument_type=itype,
                    instrument_no=rnd_label(rng, (ref_prefix or method[:3]).upper()),
                    instrument_date=dtstr(dt),
                    deposited_date=None,
                    cleared_date=(dtstr(dt) if state == "cleared" else None),
                    clearing_state=state,
                    ref_no=rnd_label(rng, "REF"),
                    notes=None,
                    date=dtstr(dt),
                    created_by=ids["ops_user"],
                )

            # Payments
            if scen == "bt_full_cleared":
                record_payment(total, "Bank Transfer", "cleared", when, vendor_acct_required=True)
            elif scen == "bt_partial_cleared":
                amt = round(total * rng.uniform(0.1, 0.8), 2)
                record_payment(amt, "Bank Transfer", "cleared", when, vendor_acct_required=True)
            elif scen == "chq_pending":
                amt = round(total * rng.uniform(0.2, 0.6), 2)
                record_payment(amt, "Cheque", "pending", when, vendor_acct_required=True, instrument_type="cross_cheque")
            elif scen == "chq_clear_later":
                amt = round(total * rng.uniform(0.2, 0.7), 2)
                pay_id = record_payment(amt, "Cheque", "pending", when, vendor_acct_required=True, instrument_type="cross_cheque")
                if pay_id:
                    ppay.update_clearing_state(pay_id, clearing_state="cleared", cleared_date=dtstr(when + timedelta(days=rng.randint(2, 10))))
            elif scen == "dep_clear_later":
                amt = round(total * rng.uniform(0.1, 0.6), 2)
                pay_id = record_payment(amt, "Cash Deposit", "pending", when, vendor_acct_required=True, instrument_type="cash_deposit")
                if pay_id:
                    ppay.update_clearing_state(pay_id, clearing_state="cleared", cleared_date=dtstr(when + timedelta(days=rng.randint(1, 5))))
            elif scen == "dep_bounced":
                amt = round(total * rng.uniform(0.1, 0.6), 2)
                pay_id = record_payment(amt, "Cash Deposit", "pending", when, vendor_acct_required=True, instrument_type="cash_deposit")
                if pay_id:
                    ppay.update_clearing_state(pay_id, clearing_state="bounced", cleared_date=dtstr(when + timedelta(days=rng.randint(1, 7))))
            elif scen == "late_bt_cleared":
                amt = round(total * rng.uniform(0.3, 0.9), 2)
                later = when + timedelta(days=rng.randint(3, 20))
                record_payment(amt, "Bank Transfer", "cleared", later, vendor_acct_required=True)
            elif scen == "cash_full_posted":
                record_payment(total, "Cash", "posted", when, vendor_acct_required=False)
            elif scen == "cash_partial_posted":
                amt = round(total * rng.uniform(0.1, 0.9), 2)
                record_payment(amt, "Cash", "posted", when, vendor_acct_required=False)
            # else: "none" → no initial payment

            # Returns
            rscen = maybe_return_scenario(i, rng)
            if rscen:
                rows = list_items(con, pid)
                if rows:
                    chosen = rng.sample(rows, k=1 if len(rows) == 1 else rng.randint(1, min(2, len(rows))))
                    lines = []
                    for r in chosen:
                        q_orig = float(r["qty"])
                        if q_orig <= 0:
                            continue
                        q_ret = max(1.0, round(q_orig * rng.uniform(0.2, 0.6)))
                        q_ret = min(q_ret, q_orig)
                        if q_ret < 0.01:
                            continue
                        lines.append({
                            "item_id": int(r["item_id"]),
                            "product_id": int(r["product_id"]),
                            "uom_id": int(r["uom_id"]),
                            "qty_return": float(q_ret),
                        })
                    if lines:
                        if rscen == "credit_note":
                            settlement = {"mode": "credit_note"}
                            PurchasesRepo(con).record_return(
                                pid=pid,
                                date=dtstr(when + timedelta(days=rng.randint(1, 30))),
                                created_by=ids["ops_user"],
                                lines=lines,
                                notes=None,
                                settlement=settlement,
                            )
                        else:
                            settle = {
                                "mode": "refund_now",
                                "method": "Bank Transfer",
                                "bank_account_id": ids["company_meezan"],
                                "vendor_bank_account_id": None,
                                "instrument_type": "online",
                                "instrument_no": rnd_label(rng, "RFN"),
                            }
                            try:
                                PurchasesRepo(con).record_return(
                                    pid=pid,
                                    date=dtstr(when + timedelta(days=rng.randint(1, 30))),
                                    created_by=ids["ops_user"],
                                    lines=lines,
                                    notes=None,
                                    settlement=settle,
                                )
                            except Exception:
                                settle["mode"] = "refund"
                                PurchasesRepo(con).record_return(
                                    pid=pid,
                                    date=dtstr(when + timedelta(days=rng.randint(1, 30))),
                                    created_by=ids["ops_user"],
                                    lines=lines,
                                    notes=None,
                                    settlement=settle,
                                )

            # Optional credit application
            if rng.random() < 0.15:
                paid, due = po_paid_and_due(con, pid)
                if due > 1e-6:
                    bal = float(vadv.get_balance(vid))
                    if bal > 1e-6:
                        raw_amt = min(due, bal, max(20.0, due * rng.uniform(0.2, 1.0)))
                        amt = round(raw_amt + 1e-9, 2)
                        if amt >= 0.01:
                            try:
                                vadv.apply_credit_to_purchase(
                                    vendor_id=vid, purchase_id=pid, amount=amt,
                                    date=dtstr(when + timedelta(days=rng.randint(0, 20))),
                                    notes="seed apply", created_by=ids["ops_user"]
                                )
                            except (sqlite3.IntegrityError, ValueError):
                                pass

        # Back-dated purchases for valuation_dirty on a subset of products
        print("Creating back-dated purchases for valuation_dirty signals…")
        subset = rng.sample(product_ids, k=max(10, len(product_ids)//10))
        for pid_prod in subset:
            later = base_start + timedelta(days=330)
            _ = create_purchase(
                con, pr, rng.choice(vendor_ids), later,
                items_spec=[{
                    "product_id": pid_prod,
                    "qty": rng.randint(1, 5),
                    "uom_id": ids["uom_piece"],
                    "buy": 90.0,
                    "sale": 100.0,
                    "disc": 0.0,
                }],
                created_by=ids["ops_user"]
            )
            earlier = base_start + timedelta(days=310)
            _ = create_purchase(
                con, pr, rng.choice(vendor_ids), earlier,
                items_spec=[{
                    "product_id": pid_prod,
                    "qty": rng.randint(1, 5),
                    "uom_id": ids["uom_piece"],
                    "buy": 80.0,
                    "sale": 100.0,
                    "disc": 0.0,
                }],
                created_by=ids["ops_user"]
            )

        con.commit()

        # ---- Summary ----
        npo   = con.execute("SELECT COUNT(*) AS c FROM purchases").fetchone()["c"]
        npi   = con.execute("SELECT COUNT(*) AS c FROM purchase_items").fetchone()["c"]
        npay  = con.execute("SELECT COUNT(*) AS c FROM purchase_payments").fetchone()["c"]
        nvadv = con.execute("SELECT COUNT(*) AS c FROM vendor_advances").fetchone()["c"]
        nret  = count_returns(con)

        print("Done.")
        print(f"Purchases: {npo}")
        print(f"Purchase items: {npi}")
        print(f"Payments: {npay}")
        print(f"Vendor advances rows: {nvadv}")
        print(f"Purchase returns (inventory_transactions): {nret}")

        rows = payments_summary(con)
        if rows:
            print("\nPayments by method and clearing_state:")
            for r in rows:
                print(f"  {r['method']:<14} {r['clearing_state'] or '(none)':<8}"
                      f" count={r['n']:<5} out={r['outgoing_total']:<12} in={r['incoming_total']:<12}")

    finally:
        con.close()

# ----------------------------
# CLI
# ----------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/myshop.db", help="Path to SQLite DB (existing schema required)")
    ap.add_argument("--pos", type=int, default=1000, help="How many purchases to create")
    ap.add_argument("--vendors", type=int, default=10, help="How many vendors to create")
    ap.add_argument("--products", type=int, default=100, help="How many products to create")
    ap.add_argument("--seed", type=int, default=20250101, help="Deterministic randomness seed")
    args = ap.parse_args()
    seed_everything(args.db, args.pos, args.vendors, args.products, args.seed)
