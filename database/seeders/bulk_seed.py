#!/usr/bin/env python3
"""
Bulk seeding script for the provided schema.py (PySide6 + SQLite).

This matches column names and constraints EXACTLY as defined in your schema:
- TEXT PKs for purchases.purchase_id / sales.sale_id
- Header totals: total_amount, order_discount (numeric), payment_status, paid_amount, advance_payment_applied
- Line discounts are per-unit numeric (item_discount)
- purchase_items uses base UoM only (triggers enforce this)
- sale_items can use base or alternates (mapping exists)
- Method/instrument/clearing enumerations align with schema triggers
- No payments on quotations (trigger enforces)
- All UNIQUE/INDEX/trigger constraints respected

Row targets (exact):
- company_info: 1; company_contacts: 3
- users: 30
- uoms: 14
- products: 2,000
- product_uoms: 8,000 (1 base + 3 alternates per product)
- vendors: 220
- vendor_bank_accounts: 308 (1 primary per vendor + ~40% with 1 extra)
- customers: 400
- company_bank_accounts: 6

- purchases: 18,000
- purchase_items: 54,000 lines (2/3/4 per order equally)
- sales (incl. quotations): 24,000 (2,400 quotations across 5 statuses)
- sale_items: 72,000 lines

Payments (respect method/instrument rules + clearing states):
- sale_payments rows: 28,800 (against real sales only)
- purchase_payments rows: 23,552
  - Purchases split: 12,352 paid with 1 payment; 5,600 partial with 2 payments; 48 unpaid (0 rows)

Advances (credit ledgers; trigger-safe):
- vendor_advances: 2,554 (streamed inserts; vendor→purchase matched; live remaining-due clamp)
- customer_advances: 2,780 (streamed inserts; customer→sale matched; live remaining-due clamp)

Other:
- expenses: 3,200 across 16 categories
- audit_logs: 120,000
- error_logs: 400
"""
from __future__ import annotations

import argparse
import sqlite3
import random
import math
import itertools
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Tuple, Dict, Any

# -----------------------------
# Config
# -----------------------------

CONFIG = {
    "PRAGMA": {
        "journal_mode": "WAL",
        "foreign_keys": 1,
        "synchronous": "NORMAL",
        "temp_store": "MEMORY",
        "cache_size": -200000
    },
    "COUNTS": {
        "users": 30,
        "uoms": 14,
        "products": 2000,
        "product_uoms_per_product": 4,  # 1 base + 3 alternates
        "vendors": 220,
        "customers": 400,
        "company_bank_accounts": 6,
        "purchases": 18000,
        "sales": 24000,
        "sale_payments": 28800,
        "purchase_payments": 23552,
        "vendor_advances": 2554,
        "customer_advances": 2780,
        "expense_categories": 16,
        "expenses": 3200,
        "audit_logs": 120000,
        "error_logs": 400
    },
    "DISCOUNTS": {
        "po_level_mix": {"none": 5400, "header_only": 5400, "line_only": 4500, "both": 2700},
        "so_level_mix": {"none": 6000, "header_only": 8400, "line_only": 6000, "both": 3600},
        "header_percent_values": [2.5, 5.0, 7.5, 10.0, 15.0, 25.0],
        "header_fixed_values":   [5.0, 10.0, 25.0, 50.0, 100.0],
        "line_percent_values":   [2.5, 5.0, 10.0, 15.0, 25.0, 50.0],
        "line_fixed_values":     [0.5, 1.0, 2.0, 5.0, 10.0],
        "po_header_type_split": {"percent": 0.60, "fixed": 0.40},
        "so_header_type_split": {"percent": 0.65, "fixed": 0.35},
        "po_line_percent_share": 0.70,
        "so_line_percent_share": 0.75
    },
    "UOMS": [
        "Each","Box","Kilogram","Gram","Liter","Milliliter",
        "Pack","Dozen","Meter","Centimeter","Inch","Foot","Pair","Set"
    ],
    "PRICING": {
        "purchase_price_min": 5.0,
        "purchase_price_max": 300.0,
        "markup_min": 1.15,
        "markup_max": 1.50,
        "sale_unit_price_min": 6.0,
        "sale_unit_price_max": 500.0,
        "qty_min": 1,
        "qty_max": 20
    },
    "DATES": {
        "days_back": 365
    },
    "PAYMENTS": {
        "methods": ["Cash","Bank Transfer","Card","Cheque","Cash Deposit","Other"],
        # instrument types allowed by schema
        "instrument_types": ["online","cross_cheque","cash_deposit","pay_order","other"],
        "clearing_states": ["posted","pending","cleared","bounced"],
        "purchases_paid_one": 12352,
        "purchases_partial_two": 5600,
        "purchases_unpaid": 48
    }
}

def set_pragmas(conn: sqlite3.Connection):
    cur = conn.cursor()
    for k, v in CONFIG["PRAGMA"].items():
        cur.execute(f"PRAGMA {k}={v}")
    conn.commit()

def random_date_within(days_back: int, rng: random.Random) -> str:
    # aware dates not necessary; stored as DATE in schema
    dt = datetime.utcnow() - timedelta(days=rng.randint(0, days_back), seconds=rng.randint(0, 86399))
    return dt.strftime("%Y-%m-%d")

def money(val: float) -> float:
    return round(float(val), 2)

def sha256_text(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def ensure_tables(conn: sqlite3.Connection):
    need = [
        "company_info","company_contacts",
        "users",
        "vendors","customers",
        "expense_categories","expenses",
        "uoms","products","product_uoms",
        "purchases","purchase_items",
        "sales","sale_items",
        "company_bank_accounts","vendor_bank_accounts",
        "sale_payments","purchase_payments",
        "customer_advances","vendor_advances",
        "audit_logs","error_logs"
    ]
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    have = {r[0] for r in cur.fetchall()}
    missing = [t for t in need if t not in have]
    if missing:
        raise SystemExit(f"Missing tables from schema: {missing}")

# ----------------------------------
# Seed functions
# ----------------------------------

def seed_company(conn, rng, commit_size):
    # company_info
    conn.execute(
        "INSERT OR IGNORE INTO company_info (company_id, company_name, address, logo_path) VALUES (1,?,?,?)",
        ("Acme Trading Ltd.", "1 High Street, Metropolis", "/assets/logo.png")
    )
    # company_contacts (exactly 3 rows; 1 primary)
    rows = [
        (1, "phone", "+92-000-0000000", 1),
        (1, "email", "info@acmetrading.test", 0),
        (1, "website", "https://acmetrading.test", 0),
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO company_contacts (company_id, contact_type, contact_value, is_primary) VALUES (?,?,?,?)",
        rows
    )
    conn.commit()

def seed_users(conn, rng, commit_size):
    rows = []
    roles = ["admin","manager","clerk","viewer"]
    for i in range(CONFIG["COUNTS"]["users"]):
        uname = f"user{i+1:03d}"
        pwd = sha256_text(f"pass:{uname}")
        rows.append((uname, pwd, f"User {i+1:03d}", f"{uname}@acmetrading.test", roles[i % len(roles)], 1))
    conn.executemany(
        "INSERT OR IGNORE INTO users (username, password_hash, full_name, email, role, is_active) VALUES (?,?,?,?,?,?)",
        rows
    )
    conn.commit()

def seed_uoms(conn, rng, commit_size) -> Dict[str,int]:
    rows = [(nm,) for nm in CONFIG["UOMS"]]
    conn.executemany("INSERT OR IGNORE INTO uoms (unit_name) VALUES (?)", rows)
    conn.commit()
    cur = conn.execute("SELECT uom_id, unit_name FROM uoms")
    return {name: uid for (uid, name) in cur.fetchall()}

def seed_products(conn, rng, commit_size) -> Dict[int, Dict[str, Any]]:
    categories = ["Raw","Finished","Accessory","Service","Spare"]
    rows = []
    for i in range(CONFIG["COUNTS"]["products"]):
        name = f"Product {i+1:04d}"
        desc = f"Description for {name}"
        cat = categories[i % len(categories)]
        minlvl = money(rng.uniform(0, 50))
        rows.append((name, desc, cat, minlvl))
    conn.executemany(
        "INSERT INTO products (name, description, category, min_stock_level) VALUES (?,?,?,?)", rows
    )
    conn.commit()
    cur = conn.execute("SELECT product_id, name FROM products ORDER BY product_id")
    return {pid: {"name": nm} for (pid, nm) in cur.fetchall()}

def seed_product_uoms(conn, rng, uom_ids: Dict[str,int], products: Dict[int, Dict[str,Any]]):
    # Base + 3 alternates per product; respect unique base constraint
    alt_factors = [0.5, 2.0, 10.0]  # >0; base = 1.0
    uom_names = list(uom_ids.keys())

    # insert bases first with INSERT OR IGNORE to allow re-runs safely
    base_rows = []
    for idx, pid in enumerate(products.keys()):
        base_name = uom_names[idx % len(uom_names)]
        base_id = uom_ids[base_name]
        base_rows.append((pid, base_id, 1, 1.0))
    conn.executemany(
        "INSERT OR IGNORE INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?,?,?,?)",
        base_rows
    )
    conn.commit()

    # insert alternates (ignore duplicates on product_id,uom_id)
    alt_rows = []
    for idx, pid in enumerate(products.keys()):
        for j, f in enumerate(alt_factors):
            alt_name = uom_names[(idx + j + 1) % len(uom_names)]
            alt_rows.append((pid, uom_ids[alt_name], 0, float(f)))
    conn.executemany(
        "INSERT OR IGNORE INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?,?,?,?)",
        alt_rows
    )
    conn.commit()

def fetch_ids(conn, table, id_col) -> List[int]:
    cur = conn.execute(f"SELECT {id_col} FROM {table} ORDER BY {id_col}")
    return [r[0] for r in cur.fetchall()]

def seed_parties_and_banks(conn, rng):
    # Vendors
    vrows = []
    for i in range(CONFIG["COUNTS"]["vendors"]):
        nm = f"Vendor {i+1:03d}"
        contact = f"vendor{i+1:03d}@mail.test | +92-3{i%10}{i%10}-{1000000+i:07d}"
        addr = f"{i+1} Vendor Street, City"
        vrows.append((nm, contact, addr))
    conn.executemany("INSERT INTO vendors (name, contact_info, address) VALUES (?,?,?)", vrows)

    # Customers
    crows = []
    for i in range(CONFIG["COUNTS"]["customers"]):
        nm = f"Customer {i+1:03d}"
        contact = f"customer{i+1:03d}@mail.test | +92-30{i%10}-{2000000+i:07d}"
        addr = f"{i+1} Customer Avenue, City"
        crows.append((nm, contact, addr, 1))
    conn.executemany("INSERT INTO customers (name, contact_info, address, is_active) VALUES (?,?,?,?)", crows)

    # Company bank accounts
    brows = []
    for i in range(CONFIG["COUNTS"]["company_bank_accounts"]):
        brows.append((1, f"Operating-{i+1}", f"Bank {i+1}", f"{rng.randint(10_000_000,99_999_999)}",
                      f"IBAN{rng.randint(1_000_000_000,9_999_999_999)}", None, 1))
    conn.executemany(
        "INSERT OR IGNORE INTO company_bank_accounts (company_id, label, bank_name, account_no, iban, routing_no, is_active) VALUES (?,?,?,?,?,?,?)",
        brows
    )

    conn.commit()

    # Vendor bank accounts: 1 primary each + extra for ~40% with non-primary
    vendor_ids = fetch_ids(conn, "vendors", "vendor_id")
    vb_rows = []
    for vid in vendor_ids:
        vb_rows.append((vid, f"Primary-{vid}", f"Bank V{vid}", f"{rng.randint(10_000_00,99_999_999)}",
                        f"VIB{rng.randint(1_000_000_000,9_999_999_999)}", None, 1, 1))
    extra_count = int(round(len(vendor_ids)*0.40))
    extra_sample = random.Random(rng.randint(0,10**9)).sample(vendor_ids, extra_count)
    for vid in extra_sample:
        vb_rows.append((vid, f"Extra-{vid}", f"Bank VX{vid}", f"{rng.randint(10_000_00,99_999_999)}",
                        f"VIB{rng.randint(1_000_000_000,9_999_999_999)}", None, 0, 1))
    conn.executemany(
        "INSERT OR IGNORE INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active) VALUES (?,?,?,?,?,?,?,?)",
        vb_rows
    )
    conn.commit()

def build_uom_maps(conn):
    # product base/alternate uoms
    base = {}
    alts = defaultdict(list)
    cur = conn.execute("SELECT product_id, uom_id, is_base FROM product_uoms")
    for pid, uid, is_base in cur.fetchall():
        if is_base:
            base[pid] = uid
        else:
            alts[pid].append(uid)
    return base, alts

def price_qty_for_purchase(rng):
    pmin = CONFIG["PRICING"]["purchase_price_min"]
    pmax = CONFIG["PRICING"]["purchase_price_max"]
    qty = rng.randint(CONFIG["PRICING"]["qty_min"], CONFIG["PRICING"]["qty_max"])
    pprice = money(rng.uniform(pmin, pmax))
    # sale price as markup on purchase price
    markup = rng.uniform(CONFIG["PRICING"]["markup_min"], CONFIG["PRICING"]["markup_max"])
    sprice = money(pprice * markup)
    return pprice, sprice, qty

def price_qty_for_sale(rng):
    smin = CONFIG["PRICING"]["sale_unit_price_min"]
    smax = CONFIG["PRICING"]["sale_unit_price_max"]
    qty = rng.randint(CONFIG["PRICING"]["qty_min"], CONFIG["PRICING"]["qty_max"])
    unit = money(rng.uniform(smin, smax))
    return unit, qty

def allocate_order_header_discounts(rng, count, level_mix, header_split, pct_values, fix_values):
    assert sum(level_mix.values()) == count
    header_total = level_mix["header_only"] + level_mix["both"]
    pct_n = int(round(header_total * header_split["percent"]))
    fix_n = header_total - pct_n

    # Build pools with even distribution per value
    def spread(values, n):
        base = n // len(values)
        rem = n - base * len(values)
        out = []
        for i, v in enumerate(values):
            out += [v] * (base + (1 if i < rem else 0))
        rng.shuffle(out)
        return out

    pool_pct = [("percent", v) for v in spread(pct_values, pct_n)]
    pool_fix = [("fixed", v) for v in spread(fix_values, fix_n)]
    header_pool = pool_pct + pool_fix
    rng.shuffle(header_pool)

    # Compose assignments
    assigns = []
    seq = (["none"] * level_mix["none"] +
           ["header_only"] * level_mix["header_only"] +
           ["line_only"] * level_mix["line_only"] +
           ["both"] * level_mix["both"])
    rng.shuffle(seq)
    hp = 0
    for key in seq:
        if key in ("header_only","both"):
            assigns.append({"level": key, "header": header_pool[hp]})
            hp += 1
        else:
            assigns.append({"level": key, "header": (None, None)})
    return assigns

def allocate_line_discount_pool(rng, discounted_lines, percent_share, pct_values, fix_values):
    pct_lines = int(round(discounted_lines * percent_share))
    fix_lines = discounted_lines - pct_lines
    def spread(values, n):
        base = n // len(values); rem = n - base*len(values)
        out = []
        for i, v in enumerate(values):
            out += [v] * (base + (1 if i < rem else 0))
        rng.shuffle(out); return out
    pool = [("percent", v) for v in spread(pct_values, pct_lines)]
    pool += [("fixed", v) for v in spread(fix_values, fix_lines)]
    rng.shuffle(pool)
    return pool

def seed_purchases(conn, rng, users_ids, vendor_ids, products, base_uom, commit_size):
    dcfg = CONFIG["DISCOUNTS"]
    level_mix = dcfg["po_level_mix"]
    assigns = allocate_order_header_discounts(
        rng, CONFIG["COUNTS"]["purchases"], level_mix,
        dcfg["po_header_type_split"],
        dcfg["header_percent_values"],
        dcfg["header_fixed_values"]
    )
    # 2/3/4 line distribution equal thirds
    lines_per_order = [2]*6000 + [3]*6000 + [4]*6000
    rng.shuffle(lines_per_order)

    # line discount pool for discounted lines
    discounted_orders = level_mix["line_only"] + level_mix["both"]  # 7200
    discounted_lines_target = discounted_orders * 3  # 21600
    line_pool = allocate_line_discount_pool(
        rng, discounted_lines_target, dcfg["po_line_percent_share"],
        dcfg["line_percent_values"], dcfg["line_fixed_values"]
    )
    lp_idx = 0

    purchase_ids = []
    item_rows = []

    for i in range(CONFIG["COUNTS"]["purchases"]):
        pid = f"PO-{i+1:06d}"
        vendor_id = rng.choice(vendor_ids)
        user_id = rng.choice(users_ids)
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)
        n_lines = lines_per_order[i]
        # lines
        subtotal = 0.0
        for ln in range(n_lines):
            prod_id = rng.choice(list(products.keys()))
            uom_id = base_uom[prod_id]  # base only
            pprice, sprice, qty = price_qty_for_purchase(rng)

            # per-unit item_discount (percent -> unit * p/100, fixed -> per-unit value)
            if assigns[i]["level"] in ("line_only","both") and lp_idx < len(line_pool):
                ltype, lval = line_pool[lp_idx]; lp_idx += 1
                disc_per_unit = money((pprice * (lval/100.0)) if ltype=="percent" else lval)
            else:
                ltype, lval = (None, None)
                disc_per_unit = 0.0

            net_unit = max(0.0, money(pprice - disc_per_unit))
            line_total = money(net_unit * qty)
            subtotal = money(subtotal + line_total)

            item_rows.append((pid, prod_id, qty, uom_id, pprice, sprice, disc_per_unit))

        # header order_discount -> numeric
        htype, hval = assigns[i]["header"]
        if htype is None:
            order_disc = 0.0
        elif htype == "percent":
            order_disc = min(subtotal, money(subtotal * (hval/100.0)))
        else:
            order_disc = min(subtotal, money(hval))

        total_amount = money(subtotal - order_disc)
        # initial header payment fields (triggers update later)
        conn.execute(
            "INSERT INTO purchases (purchase_id, vendor_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, notes, created_by) "
            "VALUES (?,?,?,?,?,'unpaid',0,0,?,?)",
            (pid, vendor_id, date, total_amount, order_disc, f"Auto-seeded #{i+1}", user_id)
        )
        purchase_ids.append(pid)

        if (i+1) % commit_size == 0:
            conn.commit()

    # insert items
    conn.executemany(
        "INSERT INTO purchase_items (purchase_id, product_id, quantity, uom_id, purchase_price, sale_price, item_discount) "
        "VALUES (?,?,?,?,?,?,?)",
        item_rows
    )
    conn.commit()
    return purchase_ids, len(item_rows)

def seed_sales(conn, rng, users_ids, customer_ids, products, base_uom, alt_uoms, commit_size):
    dcfg = CONFIG["DISCOUNTS"]
    level_mix = dcfg["so_level_mix"]
    assigns = allocate_order_header_discounts(
        rng, CONFIG["COUNTS"]["sales"], level_mix,
        dcfg["so_header_type_split"],
        dcfg["header_percent_values"],
        dcfg["header_fixed_values"]
    )
    # lines per order ~ equal thirds
    N = CONFIG["COUNTS"]["sales"]
    per = N // 3
    lines_per_order = [2]*per + [3]*per + [4]*(N - 2*per)
    rng.shuffle(lines_per_order)

    discounted_orders = level_mix["line_only"] + level_mix["both"]  # 9600
    discounted_lines_target = discounted_orders * 3  # 28800
    line_pool = allocate_line_discount_pool(
        rng, discounted_lines_target, dcfg["so_line_percent_share"],
        dcfg["line_percent_values"], dcfg["line_fixed_values"]
    )
    lp_idx = 0

    sale_ids = []
    item_rows = []

    # select quotation indices (exactly 2,400); distribute statuses equally
    quotation_indices = set(rng.sample(range(N), k=2400))
    q_statuses = ["draft","sent","accepted","expired","cancelled"]
    q_cycle = list(itertools.chain.from_iterable([[s]*480 for s in q_statuses]))
    rng.shuffle(q_cycle); q_idx = 0

    for i in range(N):
        sid = f"SO-{i+1:06d}"
        customer_id = rng.choice(customer_ids)
        user_id = rng.choice(users_ids)
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)
        if i in quotation_indices:
            doc_type = "quotation"
            quotation_status = q_cycle[q_idx]; q_idx += 1
        else:
            doc_type = "sale"
            quotation_status = None

        n_lines = lines_per_order[i]
        subtotal = 0.0
        for ln in range(n_lines):
            prod_id = rng.choice(list(products.keys()))
            base = base_uom[prod_id]
            alts = alt_uoms[prod_id]
            uom_id = (alts[ln % len(alts)] if alts and (ln % 2 == 1) else base)

            unit_price, qty = price_qty_for_sale(rng)
            if assigns[i]["level"] in ("line_only","both") and lp_idx < len(line_pool):
                ltype, lval = line_pool[lp_idx]; lp_idx += 1
                disc_per_unit = money((unit_price * (lval/100.0)) if ltype=="percent" else lval)
            else:
                disc_per_unit = 0.0

            net_unit = max(0.0, money(unit_price - disc_per_unit))
            line_total = money(net_unit * qty)
            subtotal = money(subtotal + line_total)

            item_rows.append((sid, prod_id, qty, uom_id, unit_price, disc_per_unit))

        # header discount numeric
        htype, hval = assigns[i]["header"]
        if htype is None:
            order_disc = 0.0
        elif htype == "percent":
            order_disc = min(subtotal, money(subtotal*(hval/100.0)))
        else:
            order_disc = min(subtotal, money(hval))

        total_amount = money(subtotal - order_disc)

        # quotation guard fields
        if doc_type == "quotation":
            payment_status = "unpaid"; paid_amount = 0.0; adv_applied = 0.0
        else:
            payment_status = "unpaid"; paid_amount = 0.0; adv_applied = 0.0

        conn.execute(
            "INSERT INTO sales (sale_id, customer_id, date, total_amount, order_discount, payment_status, paid_amount, advance_payment_applied, notes, created_by, source_type, source_id, doc_type, quotation_status, expiry_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?, 'direct', NULL, ?, ?, NULL)",
            (sid, customer_id, date, total_amount, order_disc, payment_status, paid_amount, adv_applied,
             f"Auto-seeded #{i+1}", user_id, doc_type, quotation_status)
        )
        sale_ids.append(sid)

        if (i+1) % commit_size == 0:
            conn.commit()

    # insert lines
    conn.executemany(
        "INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, unit_price, item_discount) VALUES (?,?,?,?,?,?)",
        item_rows
    )
    conn.commit()
    return sale_ids, len(item_rows)

# ---------------- Payments & Advances ----------------

def method_compatible_instrument(method: str) -> str:
    # Enforce method-specific instrument_type constraints
    if method == "Bank Transfer":
        return "online"
    if method == "Cheque":
        return "cross_cheque"
    if method == "Cash Deposit":
        return "cash_deposit"
    if method == "Card":
        return "pay_order"
    # Cash/Other: use 'other' to satisfy CHECK
    return "other"

def seed_purchase_payments(conn, rng, purchase_ids, company_bank_ids, vendor_bank_by_vendor, users_ids):
    pay = CONFIG["PAYMENTS"]
    paid_one = pay["purchases_paid_one"]
    partial_two = pay["purchases_partial_two"]
    unpaid = pay["purchases_unpaid"]
    assert paid_one + partial_two + unpaid == len(purchase_ids)

    rng.shuffle(purchase_ids)
    ids_paid = purchase_ids[:paid_one]
    ids_partial = purchase_ids[paid_one:paid_one+partial_two]
    # unpaid remainder: no rows

    rows = []

    def pick_vendor_for_purchase(pid: str) -> int:
        cur = conn.execute("SELECT vendor_id FROM purchases WHERE purchase_id=?", (pid,))
        return cur.fetchone()[0]

    def remaining_due(pid: str) -> float:
        cur = conn.execute("""
            SELECT CAST(total_amount AS REAL)
                 - COALESCE((SELECT SUM(CASE WHEN clearing_state='cleared' THEN CAST(amount AS REAL) ELSE 0 END)
                             FROM purchase_payments WHERE purchase_id=?),0)
                 - CAST(advance_payment_applied AS REAL)
            FROM purchases WHERE purchase_id=?""", (pid,pid))
        return float(cur.fetchone()[0])

    # paid (1 payment, mostly 'cleared')
    for i, pid in enumerate(ids_paid):
        method = rng.choice(pay["methods"])
        inst = method_compatible_instrument(method)
        bank_id = rng.choice(company_bank_ids) if method in ("Bank Transfer","Cheque","Cash Deposit","Card") else None
        vendor_id = pick_vendor_for_purchase(pid)
        vba_ids = vendor_bank_by_vendor.get(vendor_id, [])
        vba_id = rng.choice(vba_ids) if (method in ("Bank Transfer","Cheque","Cash Deposit") and vba_ids) else None
        amount = max(10.0, money(rng.uniform(50.0, 1200.0)))
        amount = min(amount, max(10.0, remaining_due(pid)))
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)
        clearing = rng.choices(pay["clearing_states"], weights=[1,1,8,1], k=1)[0]
        instrument_no = f"TX-{rng.randint(100000,999999)}" if method in ("Bank Transfer","Cheque","Cash Deposit","Card") else None
        rows.append((pid, date, amount, method, bank_id, vba_id, inst, instrument_no, None, None, None, clearing, None, None, rng.choice(users_ids)))

    # partial (2 payments each)
    for i, pid in enumerate(ids_partial):
        for _ in range(2):
            method = rng.choice(pay["methods"])
            inst = method_compatible_instrument(method)
            bank_id = rng.choice(company_bank_ids) if method in ("Bank Transfer","Cheque","Cash Deposit","Card") else None
            vendor_id = pick_vendor_for_purchase(pid)
            vba_ids = vendor_bank_by_vendor.get(vendor_id, [])
            vba_id = rng.choice(vba_ids) if (method in ("Bank Transfer","Cheque","Cash Deposit") and vba_ids) else None
            amount = max(5.0, money(rng.uniform(20.0, 400.0)))
            amount = min(amount, max(5.0, remaining_due(pid)))
            date = random_date_within(CONFIG["DATES"]["days_back"], rng)
            clearing = rng.choices(pay["clearing_states"], weights=[2,4,3,1], k=1)[0]
            instrument_no = f"TX-{rng.randint(100000,999999)}" if method in ("Bank Transfer","Cheque","Cash Deposit","Card") else None
            rows.append((pid, date, amount, method, bank_id, vba_id, inst, instrument_no, None, None, None, clearing, None, None, rng.choice(users_ids)))

    conn.executemany(
        "INSERT INTO purchase_payments (purchase_id, date, amount, method, bank_account_id, vendor_bank_account_id, instrument_type, instrument_no, instrument_date, deposited_date, cleared_date, clearing_state, ref_no, notes, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    return len(rows)

def seed_sale_payments(conn, rng, sale_ids, company_bank_ids, users_ids):
    target = CONFIG["COUNTS"]["sale_payments"]
    cur = conn.execute("SELECT sale_id, total_amount, paid_amount FROM sales WHERE doc_type='sale' ORDER BY sale_id")
    real_sales = cur.fetchall()
    rows = []
    si = 0
    while len(rows) < target:
        sid, total_amount, paid = real_sales[si % len(real_sales)]
        method = rng.choice(CONFIG["PAYMENTS"]["methods"])
        inst = method_compatible_instrument(method)
        bank_id = rng.choice(company_bank_ids) if method in ("Bank Transfer","Cheque","Cash Deposit","Card") else None
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)
        clearing = rng.choices(CONFIG["PAYMENTS"]["clearing_states"], weights=[6,2,2,1], k=1)[0]
        instrument_no = f"RX-{rng.randint(100000,999999)}" if method in ("Bank Transfer","Cheque","Cash Deposit","Card") else None
        amount = max(5.0, money(random.uniform(20.0, 600.0)))
        rows.append((sid, date, amount, method, bank_id, inst, instrument_no, None, None, None, clearing, None, None, rng.choice(users_ids)))
        si += 1
    conn.executemany(
        "INSERT INTO sale_payments (sale_id, date, amount, method, bank_account_id, instrument_type, instrument_no, instrument_date, deposited_date, cleared_date, clearing_state, ref_no, notes, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    return len(rows)

# ---------- FIXED: Streamed, trigger-safe advances seeding ----------

def seed_advances(conn, rng, users_ids, commit_size):
    """
    Insert vendor/customer advances in a trigger-safe way:
    - For applied rows, pick documents that belong to the same party.
    - Read remaining due LIVE just before the insert.
    - Clamp negative amounts to min(available_balance, remaining_due - 0.01).
    - Insert rows one-by-one (stream), committing periodically.
    """
    vendor_ids = fetch_ids(conn, "vendors", "vendor_id")
    customer_ids = fetch_ids(conn, "customers", "customer_id")
    v_bal = defaultdict(float)   # running vendor balance (>= 0)
    c_bal = defaultdict(float)   # running customer balance (>= 0)

    # party -> docs map (for logical matching)
    v_to_pos = defaultdict(list)
    for pid, vid in conn.execute("SELECT purchase_id, vendor_id FROM purchases"):
        v_to_pos[vid].append(pid)

    c_to_sos = defaultdict(list)
    for sid, cid in conn.execute("SELECT sale_id, customer_id FROM sales WHERE doc_type='sale'"):
        c_to_sos[cid].append(sid)

    def sale_remaining_due(sid: str) -> float:
        cur = conn.execute("""
            SELECT CAST(total_amount AS REAL) - CAST(paid_amount AS REAL) - CAST(advance_payment_applied AS REAL)
            FROM sales WHERE sale_id=?""", (sid,))
        row = cur.fetchone()
        return float(row[0]) if row else 0.0

    def purchase_remaining_due(pid: str) -> float:
        cur = conn.execute("""
            SELECT CAST(total_amount AS REAL) - CAST(paid_amount AS REAL) - CAST(advance_payment_applied AS REAL)
            FROM purchases WHERE purchase_id=?""", (pid,))
        row = cur.fetchone()
        return float(row[0]) if row else 0.0

    # --- Vendors (streamed) ---
    v_target = CONFIG["COUNTS"]["vendor_advances"]
    inserted = 0
    for _ in range(v_target):
        vid = rng.choice(vendor_ids)
        # bias toward applications but allow deposits/returns
        t = rng.choices(["deposit","applied_to_purchase","return_credit"], weights=[0.15, 0.60, 0.25], k=1)[0]
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)

        # defaults
        amt = None
        src_id = None

        if t in ("deposit", "return_credit"):
            amt = money(rng.uniform(20.0, 800.0))  # positive
            v_bal[vid] += amt
            if t == "return_credit" and v_to_pos[vid]:
                src_id = rng.choice(v_to_pos[vid])
        else:
            # applied_to_purchase: same vendor’s purchases only
            pool = v_to_pos.get(vid, [])
            if not pool:
                # no document to apply -> deposit instead
                t = "deposit"
                amt = money(rng.uniform(20.0, 400.0))
                v_bal[vid] += amt
                src_id = None
            else:
                pid = rng.choice(pool)
                due = purchase_remaining_due(pid)
                # maximum we’re allowed to apply (2-decimal money + cushion)
                max_apply = max(0.0, min(v_bal[vid], max(0.0, money(due) - 0.01)))
                if max_apply < 5.0:
                    # not worth applying; top up balance
                    t = "deposit"
                    amt = money(rng.uniform(20.0, 400.0))
                    v_bal[vid] += amt
                    src_id = None
                else:
                    amt = -money(rng.uniform(5.0, min(200.0, max_apply)))
                    v_bal[vid] += amt  # amt is negative
                    src_id = pid

        try:
            conn.execute(
                "INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type, source_id, notes, created_by) "
                "VALUES (?,?,?,?,?,?,?)",
                (vid, date, amt, t, src_id, f"Seeded {t}", rng.choice(users_ids))
            )
        except sqlite3.IntegrityError:
            # Fallback safely to a small deposit
            t = "deposit"; amt = money(rng.uniform(20.0, 200.0)); v_bal[vid] += amt; src_id = None
            conn.execute(
                "INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type, source_id, notes, created_by) "
                "VALUES (?,?,?,?,?,?,?)",
                (vid, date, amt, t, src_id, "Fallback deposit", rng.choice(users_ids))
            )

        inserted += 1
        if inserted % 1000 == 0:
            conn.commit()
    conn.commit()

    # --- Customers (streamed) ---
    c_target = CONFIG["COUNTS"]["customer_advances"]
    inserted = 0
    for _ in range(c_target):
        cid = rng.choice(customer_ids)
        t = rng.choices(["deposit","applied_to_sale","return_credit"], weights=[0.15, 0.55, 0.30], k=1)[0]
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)

        amt = None
        src_id = None

        if t in ("deposit", "return_credit"):
            amt = money(rng.uniform(20.0, 900.0))
            c_bal[cid] += amt
            if t == "return_credit" and c_to_sos[cid]:
                src_id = rng.choice(c_to_sos[cid])
        else:
            pool = c_to_sos.get(cid, [])
            if not pool:
                t = "deposit"
                amt = money(rng.uniform(20.0, 500.0))
                c_bal[cid] += amt
            else:
                sid = rng.choice(pool)
                due = sale_remaining_due(sid)
                max_apply = max(0.0, min(c_bal[cid], max(0.0, money(due) - 0.01)))
                if max_apply < 5.0:
                    t = "deposit"; amt = money(rng.uniform(20.0, 500.0)); c_bal[cid] += amt; src_id = None
                else:
                    amt = -money(rng.uniform(5.0, min(250.0, max_apply)))
                    c_bal[cid] += amt
                    src_id = sid

        try:
            conn.execute(
                "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id, notes, created_by) "
                "VALUES (?,?,?,?,?,?,?)",
                (cid, date, amt, t, src_id, f"Seeded {t}", rng.choice(users_ids))
            )
        except sqlite3.IntegrityError:
            # Fallback safely to a small deposit
            t = "deposit"; amt = money(rng.uniform(20.0, 200.0)); c_bal[cid] += amt; src_id = None
            conn.execute(
                "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id, notes, created_by) "
                "VALUES (?,?,?,?,?,?,?)",
                (cid, date, amt, t, src_id, "Fallback deposit", rng.choice(users_ids))
            )

        inserted += 1
        if inserted % 1000 == 0:
            conn.commit()
    conn.commit()

def seed_expenses(conn, rng):
    # categories
    conn.executemany("INSERT OR IGNORE INTO expense_categories (name) VALUES (?)",
                     [(f"Category {i+1:02d}",) for i in range(CONFIG['COUNTS']['expense_categories'])])
    cur = conn.execute("SELECT category_id FROM expense_categories ORDER BY category_id")
    cats = [r[0] for r in cur.fetchall()]
    # expenses
    rows = []
    for i in range(CONFIG["COUNTS"]["expenses"]):
        cat = random.choice(cats)
        desc = f"Expense {i+1:04d}"
        amt = money(random.uniform(5.0, 400.0))
        dt = random_date_within(CONFIG["DATES"]["days_back"], rng)
        rows.append((desc, amt, dt, cat))
    conn.executemany("INSERT INTO expenses (description, amount, date, category_id) VALUES (?,?,?,?)", rows)
    conn.commit()

def seed_logs(conn, rng, users_ids, purchases_ids, sales_ids):
    # audit_logs
    actions = ["create","update","delete","pay","return","adjust","login"]
    tables = ["products","purchases","sales","vendors","customers","uoms","purchase_items","sale_items"]
    rows = []
    for i in range(CONFIG["COUNTS"]["audit_logs"]):
        user = random.choice(users_ids)
        action = random.choice(actions)
        table = random.choice(tables)
        if table == "purchases":
            rec = random.choice(purchases_ids) if purchases_ids else None
        elif table == "sales":
            rec = random.choice(sales_ids) if sales_ids else None
        else:
            rec = None
        ts = datetime.utcnow() - timedelta(days=random.randint(0, CONFIG["DATES"]["days_back"]))
        rows.append((user, action, table, rec, ts.strftime("%Y-%m-%d %H:%M:%S"), f"{action} {table}", "127.0.0.1"))
    conn.executemany(
        "INSERT INTO audit_logs (user_id, action_type, table_name, record_id, action_time, details, ip_address) VALUES (?,?,?,?,?,?,?)",
        rows
    )
    # error_logs
    severities = ["info","warn","error","fatal"]
    erows = []
    for i in range(CONFIG["COUNTS"]["error_logs"]):
        user = random.choice(users_ids)
        sev = random.choices(severities, weights=[10,5,3,1], k=1)[0]
        etype = f"{sev.upper()}"
        msg = f"{sev} issue {i+1:04d}"
        ts = datetime.utcnow() - timedelta(days=random.randint(0, CONFIG["DATES"]["days_back"]))
        erows.append((ts.strftime("%Y-%m-%d %H:%M:%S"), etype, msg, None, None, sev, user))
    conn.executemany(
        "INSERT INTO error_logs (error_time, error_type, error_message, stack_trace, context, severity, user_id) VALUES (?,?,?,?,?,?,?)",
        erows
    )
    conn.commit()

# ----------------------------------
# Main
# ----------------------------------

def main():
    parser = argparse.ArgumentParser(description="Seed data for provided schema.py")
    parser.add_argument("--db", required=True, help="Path to SQLite DB")
    parser.add_argument("--commit-size", type=int, default=5000)
    parser.add_argument("--rng-seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.rng_seed)
    conn = sqlite3.connect(args.db)
    set_pragmas(conn)
    ensure_tables(conn)

    # Company + users + masters
    seed_company(conn, rng, args.commit_size)
    seed_users(conn, rng, args.commit_size)
    uom_ids = seed_uoms(conn, rng, args.commit_size)
    products = seed_products(conn, rng, args.commit_size)
    seed_product_uoms(conn, rng, uom_ids, products)

    base_uom, alt_uoms = build_uom_maps(conn)
    seed_parties_and_banks(conn, rng)

    users_ids = fetch_ids(conn, "users", "user_id")
    vendor_ids = fetch_ids(conn, "vendors", "vendor_id")
    customer_ids = fetch_ids(conn, "customers", "customer_id")
    company_bank_ids = fetch_ids(conn, "company_bank_accounts", "account_id")

    # Map vendor -> [vendor_bank_account_id]
    cur = conn.execute("SELECT vendor_bank_account_id, vendor_id FROM vendor_bank_accounts")
    vendor_bank_by_vendor = defaultdict(list)
    for vba_id, vid in cur.fetchall():
        vendor_bank_by_vendor[vid].append(vba_id)

    # Purchases + lines
    purchase_ids, po_lines = seed_purchases(conn, rng, users_ids, vendor_ids, products, base_uom, args.commit_size)
    # Sales + lines
    sale_ids, so_lines = seed_sales(conn, rng, users_ids, customer_ids, products, base_uom, alt_uoms, args.commit_size)

    # Payments
    pp_rows = seed_purchase_payments(conn, rng, purchase_ids, company_bank_ids, vendor_bank_by_vendor, users_ids)
    sp_rows = seed_sale_payments(conn, rng, sale_ids, company_bank_ids, users_ids)

    # Advances (streamed & trigger-safe)
    seed_advances(conn, rng, users_ids, args.commit_size)

    # Expenses
    seed_expenses(conn, rng)

    # Logs
    seed_logs(conn, rng, users_ids, purchase_ids, sale_ids)

    print("=== SEED SUMMARY ===")
    print(f"Purchases: {len(purchase_ids)}; Purchase lines: {po_lines}")
    print(f"Sales:     {len(sale_ids)}; Sale lines: {so_lines}")
    print(f"Purchase payments: {pp_rows}; Sale payments: {sp_rows}")
    print("Targets -> purchases=18000, po_lines=54000, sales=24000, so_lines=72000, sale_payments=28800, purchase_payments=23552")
    print("Done.")

if __name__ == "__main__":
    main()
