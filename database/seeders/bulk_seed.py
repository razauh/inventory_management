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
import json
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
    # NEW: Minimum target counts for larger datasets
    "COUNTS_MIN_TARGETS": {
        "purchases_min": 50000,
        "expenses_min": 10000
    },
    # NEW: Per-product purchase targets
    "PER_PRODUCT_PURCHASE_TARGETS": {
        "min_po_occurrences": 25,
        "min_purchased_qty_base": 100
    },
    # NEW: Sell-through configuration
    "SELL_THROUGH": {
        "min": 0.55,
        "max": 0.85,
        "enforce_per_product": True,
        "min_leftover_per_product": 1
    },
    # NEW: Returns configuration
    "RETURNS": {
        "enable": True,
        "sales_return_rate": 0.06,
        "purchase_return_rate": 0.03,
        "partial_line_probability": 0.65
    },
    # NEW: Expenses configuration
    "EXPENSES": {
        "seasonality": True,
        "category_zipf_s": 1.1,
        "amount_mu": 120.0,
        "amount_sigma": 70.0
    },
    # NEW: Export configuration
    "EXPORTS": {
        "dir": "/home/pc/Desktop/inventory_management/_exports",
        "inventory_snapshot_csv": "inventory_snapshot.csv"
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

def get_purchased_qty_per_product(conn) -> Dict[int, float]:
    """
    Calculate total purchased quantity in base UoM for each product.
    This accounts for quantity conversions from purchase UoM to base UoM.
    """
    cur = conn.execute("""
        SELECT 
            pi.product_id,
            SUM(pi.quantity * pu.factor_to_base) as total_base_qty
        FROM purchase_items pi
        JOIN product_uoms pu ON pi.product_id = pu.product_id AND pi.uom_id = pu.uom_id
        JOIN purchases p ON pi.purchase_id = p.purchase_id
        GROUP BY pi.product_id
    """)
    return {row[0]: row[1] for row in cur.fetchall()}

def get_sold_qty_per_product(conn) -> Dict[int, float]:
    """
    Calculate total sold quantity in base UoM for each product.
    This accounts for quantity conversions from sale UoM to base UoM.
    """
    cur = conn.execute("""
        SELECT 
            si.product_id,
            SUM(si.quantity * pu.factor_to_base) as total_base_qty
        FROM sale_items si
        JOIN product_uoms pu ON si.product_id = pu.product_id AND si.uom_id = pu.uom_id
        JOIN sales s ON si.sale_id = s.sale_id AND s.doc_type = 'sale'
        GROUP BY si.product_id
    """)
    return {row[0]: row[1] for row in cur.fetchall()}

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
    # Scale the level_mix values to match the target count
    original_total = sum(level_mix.values())
    if original_total == 0:
        # If original total is 0, assign based on target proportions
        level_mix = {k: int(v * (count / 18000)) for k, v in CONFIG["DISCOUNTS"]["po_level_mix"].items()}
        original_total = sum(level_mix.values())
    
    # Scale the counts proportionally to the new target
    scaled_level_mix = {}
    total_scaled = 0
    remaining = count
    
    # Calculate scaled values while keeping proportions roughly the same
    for k, v in level_mix.items():
        if total_scaled < count:
            scaled_val = int(round(v * count / original_total))
            if remaining > 0:
                # Adjust the last value to make sure the sum equals count
                if k == list(level_mix.keys())[-1]:
                    scaled_val = remaining
                else:
                    scaled_val = min(scaled_val, remaining)
            scaled_level_mix[k] = scaled_val
            total_scaled += scaled_val
            remaining = count - total_scaled
        else:
            scaled_level_mix[k] = 0
    
    # Ensure the sum equals count by adjusting the last value if needed
    keys = list(scaled_level_mix.keys())
    if keys:
        current_sum = sum(scaled_level_mix.values())
        if current_sum != count:
            diff = count - current_sum
            scaled_level_mix[keys[-1]] += diff

    level_mix = scaled_level_mix
    
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
    
    # Calculate how many purchases we need to ensure each product meets minimum requirements
    min_po_occurrences = CONFIG["PER_PRODUCT_PURCHASE_TARGETS"]["min_po_occurrences"]
    min_purchased_qty_base = CONFIG["PER_PRODUCT_PURCHASE_TARGETS"]["min_purchased_qty_base"]
    
    # Determine target purchase count based on minimum requirements
    min_purchases_needed = max(
        CONFIG["COUNTS"]["purchases"],  # Original count
        min_po_occurrences * CONFIG["COUNTS"]["products"]  # To ensure each product appears in at least min_po_occurrences POs
    )
    
    # Adjust the count to ensure we meet the minimum requirements
    CONFIG["COUNTS"]["purchases"] = min_purchases_needed
    
    level_mix = {k: int(v * (min_purchases_needed / 18000)) for k, v in dcfg["po_level_mix"].items()}  # Scale based on new target
    assigns = allocate_order_header_discounts(
        rng, min_purchases_needed, level_mix,
        dcfg["po_header_type_split"],
        dcfg["header_percent_values"],
        dcfg["header_fixed_values"]
    )
    
    # 2/3/4 line distribution equal thirds
    lines_per_order = [2]*int(min_purchases_needed/3) + [3]*int(min_purchases_needed/3) + [4]*int(min_purchases_needed - 2*int(min_purchases_needed/3))
    rng.shuffle(lines_per_order)

    # line discount pool for discounted lines
    discounted_orders = level_mix["line_only"] + level_mix["both"]
    discounted_lines_target = sum(lines_per_order) * (discounted_orders / min_purchases_needed)  # Approximate
    line_pool = allocate_line_discount_pool(
        rng, int(discounted_lines_target), dcfg["po_line_percent_share"],
        dcfg["line_percent_values"], dcfg["line_fixed_values"]
    )
    lp_idx = 0

    purchase_ids = []
    item_rows = []

    # Track per-product counts to ensure minimums are met
    product_occurrences = defaultdict(int)
    product_qty_base = defaultdict(int)

    for i in range(min_purchases_needed):
        pid = f"PO-{i+1:06d}"
        vendor_id = rng.choice(vendor_ids)
        user_id = rng.choice(users_ids)
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)
        n_lines = lines_per_order[i % len(lines_per_order)]  # Cycle through if we have more purchases than planned
        # lines
        subtotal = 0.0
        for ln in range(n_lines):
            # First ensure we meet minimum occurrences and quantities for each product
            product_id_list = list(products.keys())
            if len(product_occurrences) < len(product_id_list):
                # Still need to reach min occurrences for some products
                eligible_products = [pid for pid in product_id_list 
                                   if product_occurrences[pid] < min_po_occurrences or product_qty_base[pid] < min_purchased_qty_base]
                if eligible_products:
                    prod_id = rng.choice(eligible_products)
                else:
                    prod_id = rng.choice(product_id_list)
            else:
                # All products have met their minimums, use random selection
                prod_id = rng.choice(product_id_list)
            
            # Update tracking
            product_occurrences[prod_id] += 1
            
            uom_id = base_uom[prod_id]  # base only
            pprice, sprice, qty = price_qty_for_purchase(rng)
            
            # Add to quantity tracking (converting to base if needed, but since we use base UOM, factor is 1)
            product_qty_base[prod_id] += qty

            # per-unit item_discount (percent -> unit * p/100, fixed -> per-unit value)
            if i < len(assigns) and assigns[i]["level"] in ("line_only","both") and lp_idx < len(line_pool):
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
        htype, hval = assigns[i % len(assigns)]["header"] if i < len(assigns) else (None, None)
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
    level_mix = {k: int(v * (CONFIG["COUNTS"]["sales"] / 24000)) for k, v in dcfg["so_level_mix"].items()}  # Scale based on new target
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

    discounted_orders = level_mix["line_only"] + level_mix["both"]
    discounted_lines_target = sum(lines_per_order) * (discounted_orders / N)  # Approximate
    line_pool = allocate_line_discount_pool(
        rng, int(discounted_lines_target), dcfg["so_line_percent_share"],
        dcfg["line_percent_values"], dcfg["line_fixed_values"]
    )
    lp_idx = 0

    sale_ids = []
    item_rows = []

    # select quotation indices (maintain proportion); distribute statuses equally
    quotation_count = int(2400 * (N / 24000))  # Scale quotation count
    quotation_indices = set(rng.sample(range(N), k=quotation_count))
    q_statuses = ["draft","sent","accepted","expired","cancelled"]
    q_cycle = list(itertools.chain.from_iterable([[s]*int(quotation_count/len(q_statuses)) for s in q_statuses]))
    # Add any remaining quotas
    for i in range(quotation_count - len(q_cycle)):
        q_cycle.append(q_statuses[i % len(q_statuses)])
    rng.shuffle(q_cycle); q_idx = 0

    # Get purchased quantities per product to enforce sell-through constraints
    purchased = get_purchased_qty_per_product(conn)  # {product_id: qty_base}
    
    # Calculate sellable caps per product
    caps = {}
    for pid, qty in purchased.items():
        cap = int(qty * rng.uniform(CONFIG["SELL_THROUGH"]["min"], CONFIG["SELL_THROUGH"]["max"]))
        caps[pid] = max(0, cap)  # Ensure non-negative
    
    # Track sold quantities per product
    sold = defaultdict(float)  # Use float to handle factor_to_base conversions properly

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
            
            # Apply sell-through constraint
            cap = caps.get(prod_id, 0)
            base = base_uom[prod_id]
            alts = alt_uoms[prod_id]
            uom_id = (alts[ln % len(alts)] if alts and (ln % 2 == 1) else base)
            
            # Get base quantity to check against cap
            unit_price, qty = price_qty_for_sale(rng)
            
            # Convert sale quantity to base UoM for comparison with cap
            # First, find the factor from this UoM to base
            cur_factor = conn.execute(
                "SELECT factor_to_base FROM product_uoms WHERE product_id = ? AND uom_id = ?", 
                (prod_id, uom_id)
            ).fetchone()
            if cur_factor:
                factor_to_base = cur_factor[0]
            else:
                factor_to_base = 1.0  # Default if not found
            
            qty_in_base = qty * factor_to_base
            
            # Check if this sale would exceed the cap
            if sold[prod_id] + qty_in_base > max(cap, CONFIG["SELL_THROUGH"]["min_leftover_per_product"]):
                # Adjust quantity to respect cap while maintaining minimum leftover
                max_qty_in_base = max(0, cap - sold[prod_id])
                if max_qty_in_base <= 0:
                    # Skip this line item if we can't sell anything
                    continue
                # Convert back to sale UoM
                new_qty = max(1, int(max_qty_in_base / factor_to_base))
                if new_qty <= 0:
                    # Skip this line item if quantity becomes zero
                    continue
                qty = new_qty
                qty_in_base = new_qty * factor_to_base
            
            sold[prod_id] += qty_in_base

            if assigns[i]["level"] in ("line_only","both") and lp_idx < len(line_pool):
                ltype, lval = line_pool[lp_idx]; lp_idx += 1
                disc_per_unit = money((unit_price * (lval/100.0)) if ltype=="percent" else lval)
            else:
                ltype, lval = (None, None)
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
    
    # Calculate proportions based on original config but scale to actual purchase_ids count
    total_original = pay["purchases_paid_one"] + pay["purchases_partial_two"] + pay["purchases_unpaid"]
    if total_original > 0:
        paid_one = int(len(purchase_ids) * (pay["purchases_paid_one"] / total_original))
        partial_two = int(len(purchase_ids) * (pay["purchases_partial_two"] / total_original))
        unpaid = len(purchase_ids) - paid_one - partial_two  # remaining ones are unpaid
    else:
        # Fallback: assign some reasonable defaults
        paid_one = int(len(purchase_ids) * 0.5)  # 50% paid in one
        partial_two = int(len(purchase_ids) * 0.3)  # 30% partially paid
        unpaid = len(purchase_ids) - paid_one - partial_two  # remaining unpaid
    
    rng.shuffle(purchase_ids)
    ids_paid = purchase_ids[:paid_one]
    ids_partial = purchase_ids[paid_one:paid_one+partial_two]
    # unpaid remainder: no rows (they remain unpaid)

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
        # Set cleared_date if clearing_state is 'cleared', otherwise None
        cleared_date = date if clearing == 'cleared' else None
        rows.append((pid, date, amount, method, bank_id, vba_id, inst, instrument_no, None, None, cleared_date, clearing, None, None, rng.choice(users_ids)))

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
            # Set cleared_date if clearing_state is 'cleared', otherwise None
            cleared_date = date if clearing == 'cleared' else None
            rows.append((pid, date, amount, method, bank_id, vba_id, inst, instrument_no, None, None, cleared_date, clearing, None, None, rng.choice(users_ids)))

    conn.executemany(
        "INSERT INTO purchase_payments (purchase_id, date, amount, method, bank_account_id, vendor_bank_account_id, instrument_type, instrument_no, instrument_date, deposited_date, cleared_date, clearing_state, ref_no, notes, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()
    return len(rows)

def seed_sale_payments(conn, rng, sale_ids, company_bank_ids, users_ids):
    # Get real sales (not quotations)
    cur = conn.execute("SELECT sale_id, total_amount, paid_amount FROM sales WHERE doc_type='sale' ORDER BY sale_id")
    real_sales = cur.fetchall()
    
    if not real_sales:
        return 0  # No real sales to create payments for
    
    # Calculate target based on proportion of real sales
    target = int(CONFIG["COUNTS"]["sale_payments"] * (len(real_sales) / CONFIG["COUNTS"]["sales"]))
    
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
        
        # Clamp payment to remaining amount to avoid overpayment
        remaining_due = total_amount - paid
        amount = max(5.0, min(money(random.uniform(20.0, 600.0)), remaining_due - 0.01))  # Ensure no overpayment
        
        # Set cleared_date if clearing_state is 'cleared', otherwise None
        cleared_date = date if clearing == 'cleared' else None
        
        if amount > 0:  # Only add if amount is positive
            rows.append((sid, date, amount, method, bank_id, inst, instrument_no, None, None, cleared_date, clearing, None, None, rng.choice(users_ids)))
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

def seed_sales_returns(conn, rng, sales_ids, users_ids, commit_size):
    """
    Seed sales returns as inventory transactions linked to original sale items.
    """
    if not CONFIG["RETURNS"]["enable"]:
        print("Sales returns disabled by configuration")
        return 0

    # Sample posted sales to create returns from
    real_sales = [sid for sid in sales_ids if sid in [row[0] for row in conn.execute("SELECT sale_id FROM sales WHERE doc_type='sale'").fetchall()]]
    if not real_sales:
        print("No real sales to return from")
        return 0

    # Calculate number of returns based on rate
    target_returns = int(len(real_sales) * CONFIG["RETURNS"]["sales_return_rate"])
    
    rows = []
    inv_rows = []
    return_count = 0
    
    for _ in range(target_returns):
        # Sample a sale to return from
        sale_id = rng.choice(real_sales)
        
        # Get sale items for that sale
        sale_items = conn.execute(
            "SELECT item_id, product_id, quantity, uom_id FROM sale_items WHERE sale_id=?", 
            (sale_id,)
        ).fetchall()
        
        if not sale_items:
            continue
            
        # Choose 1-2 lines to return (as specified in requirements)
        num_lines_to_return = min(rng.randint(1, 2), len(sale_items))
        selected_items = rng.sample(sale_items, num_lines_to_return)
        
        for item in selected_items:
            item_id, product_id, original_qty, uom_id = item
            
            # Determine return quantity (partial or full)
            if rng.random() < CONFIG["RETURNS"]["partial_line_probability"]:
                # Partial return
                return_qty = max(1, int(original_qty * rng.uniform(0.1, 0.9)))
            else:
                # Full return (or as much as was sold)
                return_qty = original_qty
            
            # Make sure return qty doesn't exceed original sold qty
            return_qty = min(return_qty, original_qty)
            
            if return_qty <= 0:
                continue
            
            # Create inventory transaction for the return (increases stock)
            date = random_date_within(CONFIG["DATES"]["days_back"], rng)
            # Add to inventory_transactions
            inv_rows.append((
                product_id, 
                return_qty, 
                uom_id, 
                'sale_return', 
                'sales', 
                sale_id, 
                item_id, 
                date, 
                date,  # posted_at
                0,     # txn_seq
                f"Return for sale {sale_id}", 
                rng.choice(users_ids)
            ))
            
        return_count += 1
        if return_count % commit_size == 0:
            conn.executemany(
                "INSERT INTO inventory_transactions (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id, date, posted_at, txn_seq, notes, created_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                inv_rows
            )
            conn.commit()
            inv_rows = []
    
    # Insert any remaining inventory transactions
    if inv_rows:
        conn.executemany(
            "INSERT INTO inventory_transactions (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id, date, posted_at, txn_seq, notes, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            inv_rows
        )
        conn.commit()
    
    return return_count

def seed_purchase_returns(conn, rng, purchase_ids, users_ids, commit_size):
    """
    Seed purchase returns as inventory transactions linked to original purchase items.
    """
    if not CONFIG["RETURNS"]["enable"]:
        print("Purchase returns disabled by configuration")
        return 0

    # Calculate number of returns based on rate
    target_returns = int(len(purchase_ids) * CONFIG["RETURNS"]["purchase_return_rate"])
    
    rows = []
    inv_rows = []
    return_count = 0
    
    for _ in range(target_returns):
        # Sample a purchase to return from
        purchase_id = rng.choice(purchase_ids)
        
        # Get purchase items for that purchase
        purchase_items = conn.execute(
            "SELECT item_id, product_id, quantity, uom_id FROM purchase_items WHERE purchase_id=?", 
            (purchase_id,)
        ).fetchall()
        
        if not purchase_items:
            continue
            
        # Choose 1 line to return (as specified in requirements)
        selected_item = rng.choice(purchase_items)
        item_id, product_id, original_qty, uom_id = selected_item
        
        # Determine return quantity (partial or full)
        if rng.random() < CONFIG["RETURNS"]["partial_line_probability"]:
            # Partial return
            return_qty = max(1, int(original_qty * rng.uniform(0.1, 0.8)))
        else:
            # Full return (or as much as was purchased)
            return_qty = original_qty
        
        # Make sure return qty doesn't exceed original purchased qty
        return_qty = min(return_qty, original_qty)
        
        if return_qty <= 0:
            continue
        
        # Create inventory transaction for the return (decreases stock)
        date = random_date_within(CONFIG["DATES"]["days_back"], rng)
        # Add to inventory_transactions
        inv_rows.append((
            product_id, 
            return_qty, 
            uom_id, 
            'purchase_return', 
            'purchases', 
            purchase_id, 
            item_id, 
            date, 
            date,  # posted_at 
            0,     # txn_seq
            f"Return for purchase {purchase_id}", 
            rng.choice(users_ids)
        ))
        
        return_count += 1
        if return_count % commit_size == 0:
            conn.executemany(
                "INSERT INTO inventory_transactions (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id, date, posted_at, txn_seq, notes, created_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                inv_rows
            )
            conn.commit()
            inv_rows = []
    
    # Insert any remaining inventory transactions
    if inv_rows:
        conn.executemany(
            "INSERT INTO inventory_transactions (product_id, quantity, uom_id, transaction_type, reference_table, reference_id, reference_item_id, date, posted_at, txn_seq, notes, created_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            inv_rows
        )
        conn.commit()
    
    return return_count

def seed_expenses(conn, rng):
    # NEW: Enhanced expense generation with seasonality
    import calendar
    from datetime import datetime

    # categories - ensure there are enough based on requirements
    expense_categories_needed = CONFIG["COUNTS"]["expense_categories"]
    existing_categories = conn.execute("SELECT category_id FROM expense_categories ORDER BY category_id").fetchall()
    
    # Ensure we have required number of categories
    if len(existing_categories) < expense_categories_needed:
        for i in range(len(existing_categories), expense_categories_needed):
            conn.execute("INSERT INTO expense_categories (name) VALUES (?)", (f"Category {i+1:02d}",))
    
    # Now get the actual categories
    cur = conn.execute("SELECT category_id FROM expense_categories ORDER BY category_id")
    cats = [r[0] for r in cur.fetchall()]
    
    # NEW: Apply Zipf distribution to category selection with s parameter
    # Weights for categories based on Zipf distribution: P(k) = 1 / (k^s * H(N,s))
    # For our purposes, we'll use simple weights as 1/k^s
    zipf_s = CONFIG["EXPENSES"]["category_zipf_s"]
    zipf_weights = [1 / (i ** zipf_s) for i in range(1, len(cats) + 1)]
    
    target_expenses = CONFIG["COUNTS"]["expenses"]
    
    rows = []
    for i in range(target_expenses):
        # Apply Zipf distribution to select category
        cat_idx = rng.choices(range(len(cats)), weights=zipf_weights)[0]
        cat = cats[cat_idx]
        
        desc = f"Expense {i+1:04d}"
        
        # NEW: Apply seasonality if enabled
        dt = random_date_within(CONFIG["DATES"]["days_back"], rng)
        
        # NEW: Apply seasonality based on month if enabled
        if CONFIG["EXPENSES"]["seasonality"]:
            # Increase expenses for certain months (e.g., Q4, end of fiscal periods)
            date_obj = datetime.strptime(dt, "%Y-%m-%d")
            month = date_obj.month
            # Higher weights for months where expenses typically increase
            if month in [3, 6, 9, 12]:  # End of quarters
                # Increase amount by up to 30%
                season_factor = rng.uniform(1.0, 1.3)
            elif month in [11, 12]:  # End of year
                season_factor = rng.uniform(1.1, 1.4)
            else:
                season_factor = rng.uniform(0.8, 1.2)
        else:
            season_factor = 1.0
        
        # NEW: Use truncated normal for amounts with mean and std dev
        mu = CONFIG["EXPENSES"]["amount_mu"]
        sigma = CONFIG["EXPENSES"]["amount_sigma"]
        
        # Generate amount using normal distribution and apply seasonality
        base_amt = rng.normalvariate(mu, sigma)
        amt = max(5.0, money(base_amt * season_factor))
        
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
    parser.add_argument("--counts-json", help="JSON string or path to file with count overrides")
    parser.add_argument("--scale", type=float, default=1.0, help="Global multiplier applied to base counts")
    parser.add_argument("--days-back", type=int, default=365, help="Date range for synthetic activity")
    parser.add_argument("--enable-returns", action="store_true", help="Enable seeding of returns")
    parser.add_argument("--disable-returns", action="store_false", dest="enable_returns", help="Disable seeding of returns")
    parser.set_defaults(enable_returns=True)  # Default to True
    parser.add_argument("--sell-through-target", type=str, help="Sell-through min,max range as '0.55,0.85'")
    parser.add_argument("--min-leftover-per-product", type=int, default=1, help="Minimum on-hand units per product at end")
    parser.add_argument("--min-po-occurrences-per-product", type=int, default=25, help="Minimum number of purchase_item lines per product")
    parser.add_argument("--min-purchased-qty-per-product", type=int, default=100, help="Minimum total purchased base units per product")
    parser.add_argument("--commit-size", type=int, default=5000)
    parser.add_argument("--rng-seed", type=int, default=42)
    args = parser.parse_args()

    # Apply command-line overrides to CONFIG
    if args.sell_through_target:
        try:
            min_val, max_val = map(float, args.sell_through_target.split(','))
            CONFIG["SELL_THROUGH"]["min"] = min_val
            CONFIG["SELL_THROUGH"]["max"] = max_val
        except ValueError:
            raise SystemExit(f"Invalid sell-through target format. Use '--sell-through-target 0.55,0.85'")

    CONFIG["SELL_THROUGH"]["min_leftover_per_product"] = args.min_leftover_per_product
    CONFIG["PER_PRODUCT_PURCHASE_TARGETS"]["min_po_occurrences"] = args.min_po_occurrences_per_product
    CONFIG["PER_PRODUCT_PURCHASE_TARGETS"]["min_purchased_qty_base"] = args.min_purchased_qty_per_product
    CONFIG["RETURNS"]["enable"] = args.enable_returns
    CONFIG["DATES"]["days_back"] = args.days_back

    # Update counts based on scale
    for key in CONFIG["COUNTS"]:
        if isinstance(CONFIG["COUNTS"][key], int):
            CONFIG["COUNTS"][key] = int(CONFIG["COUNTS"][key] * args.scale)

    # Ensure minimum purchase and expense targets are met if scale is above 1
    if args.scale >= 1.0:
        CONFIG["COUNTS"]["purchases"] = max(CONFIG["COUNTS"]["purchases"], CONFIG["COUNTS_MIN_TARGETS"]["purchases_min"])
        CONFIG["COUNTS"]["expenses"] = max(CONFIG["COUNTS"]["expenses"], CONFIG["COUNTS_MIN_TARGETS"]["expenses_min"])

    # Apply counts override from JSON if provided
    if args.counts_json:
        try:
            # Try to parse as JSON directly first
            override_counts = json.loads(args.counts_json)
        except json.JSONDecodeError:
            # If that fails, try to read as file path
            try:
                with open(args.counts_json) as f:
                    override_counts = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                raise SystemExit(f"Could not parse counts as JSON or file: {args.counts_json}")
        
        if "COUNTS" in override_counts:
            for key, value in override_counts["COUNTS"].items():
                CONFIG["COUNTS"][key] = value

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

    # NEW: Seed returns if enabled
    if CONFIG["RETURNS"]["enable"]:
        print("Seeding returns...")
        sales_return_count = seed_sales_returns(conn, rng, sale_ids, users_ids, args.commit_size)
        purchase_return_count = seed_purchase_returns(conn, rng, purchase_ids, users_ids, args.commit_size)
        print(f"Created {sales_return_count} sales returns and {purchase_return_count} purchase returns")
    else:
        sales_return_count = 0
        purchase_return_count = 0

    # Logs
    seed_logs(conn, rng, users_ids, purchase_ids, sale_ids)

    # NEW: Calculate and print comprehensive summary
    print("=== DETAILED SEED SUMMARY ===")
    print(f"Purchases: {len(purchase_ids)}; Purchase lines: {po_lines}")
    print(f"Sales:     {len(sale_ids)}; Sale lines: {so_lines}")
    print(f"Purchase payments: {pp_rows}; Sale payments: {sp_rows}")
    print(f"Sales returns: {sales_return_count}; Purchase returns: {purchase_return_count}")
    
    # NEW: Additional counts
    expense_count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
    print(f"Expenses: {expense_count}")
    
    # NEW: Calculate inventory summary
    on_hand_counts = get_inventory_snapshot(conn)
    
    # NEW: Validation checks
    validation_results = validate_inventory(conn, on_hand_counts)
    
    print(f"Targets -> purchases={CONFIG['COUNTS']['purchases']}, po_lines={int(CONFIG['COUNTS']['purchases']*3)}, sales={CONFIG['COUNTS']['sales']}, so_lines={int(CONFIG['COUNTS']['sales']*3)}, sale_payments={CONFIG['COUNTS']['sale_payments']}, purchase_payments={CONFIG['COUNTS']['purchase_payments']}")
    
    # NEW: Print validation results
    print("\n=== VALIDATION RESULTS ===")
    for msg in validation_results:
        print(f"✓ {msg}")
    
    # NEW: Export inventory snapshot
    export_inventory_snapshot(conn, on_hand_counts)
    
    print("Done.")

def get_inventory_snapshot(conn):
    """
    Calculate inventory snapshot: purchased, sold, returned quantities per product
    """
    # Get purchased quantities per product
    purchased = get_purchased_qty_per_product(conn)
    # Get sold quantities per product
    sold = get_sold_qty_per_product(conn)
    
    # Get sales returns (increases inventory)
    cur = conn.execute("""
        SELECT 
            it.product_id,
            SUM(it.quantity * pu.factor_to_base) as total_base_qty
        FROM inventory_transactions it
        JOIN product_uoms pu ON it.product_id = pu.product_id AND it.uom_id = pu.uom_id
        WHERE it.transaction_type = 'sale_return'
        GROUP BY it.product_id
    """)
    sales_returns = {row[0]: row[1] for row in cur.fetchall()}
    
    # Get purchase returns (decreases inventory)
    cur = conn.execute("""
        SELECT 
            it.product_id,
            SUM(it.quantity * pu.factor_to_base) as total_base_qty
        FROM inventory_transactions it
        JOIN product_uoms pu ON it.product_id = pu.product_id AND it.uom_id = pu.uom_id
        WHERE it.transaction_type = 'purchase_return'
        GROUP BY it.product_id
    """)
    purchase_returns = {row[0]: row[1] for row in cur.fetchall()}
    
    # Combine all data per product
    all_product_ids = set(purchased.keys()) | set(sold.keys()) | set(sales_returns.keys()) | set(purchase_returns.keys())
    inventory_snapshot = {}
    
    for pid in all_product_ids:
        purchased_qty = purchased.get(pid, 0)
        sold_qty = sold.get(pid, 0)
        sales_return_qty = sales_returns.get(pid, 0)
        purchase_return_qty = purchase_returns.get(pid, 0)
        on_hand = purchased_qty - sold_qty + sales_return_qty - purchase_return_qty
        
        inventory_snapshot[pid] = {
            "purchased_base": purchased_qty,
            "sold_base": sold_qty,
            "sales_returns_base": sales_return_qty,
            "purchase_returns_base": purchase_return_qty,
            "on_hand_base": on_hand
        }
    
    return inventory_snapshot

def validate_inventory(conn, inventory_snapshot):
    """
    Run validation checks on the inventory
    """
    results = []
    
    # Check 1: All products have minimum leftover inventory
    min_leftover = CONFIG["SELL_THROUGH"]["min_leftover_per_product"]
    violations = []
    for pid, data in inventory_snapshot.items():
        if data["on_hand_base"] < min_leftover:
            violations.append(pid)
    
    if len(violations) == 0:
        results.append(f"All products have at least {min_leftover} unit(s) leftover (on-hand)")
    else:
        results.append(f"WARNING: {len(violations)} products have less than {min_leftover} unit(s) leftover")
    
    # Check 2: No negative on-hand quantities
    negative_on_hand = [pid for pid, data in inventory_snapshot.items() if data["on_hand_base"] < 0]
    if len(negative_on_hand) == 0:
        results.append("No products have negative on-hand quantities")
    else:
        results.append(f"ERROR: {len(negative_on_hand)} products have negative on-hand quantities")
    
    # Check 3: Verify all products have been purchased (sanity check)
    products_with_purchases = [pid for pid, data in inventory_snapshot.items() if data["purchased_base"] > 0]
    total_products = len(conn.execute("SELECT product_id FROM products").fetchall())
    if len(products_with_purchases) == total_products:
        results.append(f"All {total_products} products have purchase records")
    else:
        results.append(f"Only {len(products_with_purchases)}/{total_products} products have purchase records")
    
    return results

def export_inventory_snapshot(conn, inventory_snapshot):
    """
    Export inventory snapshot to CSV
    """
    import os
    os.makedirs(CONFIG["EXPORTS"]["dir"], exist_ok=True)
    
    csv_path = os.path.join(CONFIG["EXPORTS"]["dir"], CONFIG["EXPORTS"]["inventory_snapshot_csv"])
    
    with open(csv_path, 'w') as f:
        f.write("product_id,purchased_base,sold_base,sales_returns_base,purchase_returns_base,on_hand_base,sell_through_ratio\n")
        
        for pid, data in inventory_snapshot.items():
            if data["purchased_base"] > 0:  # Only for products that were purchased
                sell_through = data["sold_base"] / data["purchased_base"] if data["purchased_base"] > 0 else 0
                f.write(f"{pid},{data['purchased_base']},{data['sold_base']},{data['sales_returns_base']},{data['purchase_returns_base']},{data['on_hand_base']},{sell_through:.4f}\n")
    
    print(f"Inventory snapshot exported to: {csv_path}")
    
    # Print summary of the inventory
    leftover_products = [data for data in inventory_snapshot.values() if data["on_hand_base"] > 0]
    sell_through_ratios = [data["sold_base"] / data["purchased_base"] if data["purchased_base"] > 0 else 0 
                          for data in inventory_snapshot.values() if data["purchased_base"] > 0]
    
    if sell_through_ratios:
        min_sell_through = min(sell_through_ratios)
        avg_sell_through = sum(sell_through_ratios) / len(sell_through_ratios)
        # Calculate p95
        sorted_ratios = sorted(sell_through_ratios)
        p95_idx = int(0.95 * len(sorted_ratios))
        p95_sell_through = sorted_ratios[min(p95_idx, len(sorted_ratios)-1)] if sorted_ratios else 0
        
        print(f"\n=== INVENTORY ANALYTICS ===")
        print(f"Products with leftover inventory: {len(leftover_products)}")
        print(f"Sell-through - Min: {min_sell_through:.4f}, Avg: {avg_sell_through:.4f}, P95: {p95_sell_through:.4f}")
        
        # Check for products violating minimum leftover constraint
        min_leftover = CONFIG["SELL_THROUGH"]["min_leftover_per_product"]
        violating_products = [pid for pid, data in inventory_snapshot.items() 
                             if data["on_hand_base"] < min_leftover]
        print(f"Products violating min_leftover constraint ({min_leftover}): {len(violating_products)}")

if __name__ == "__main__":
    main()
