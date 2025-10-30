from pathlib import Path
import sqlite3
import sys

SQL = r"""
PRAGMA foreign_keys = ON;

/* ======================== CORE TABLES ======================== */

/* -------- company -------- */
CREATE TABLE IF NOT EXISTS company_info (
    company_id   INTEGER PRIMARY KEY CHECK (company_id = 1),
    company_name TEXT NOT NULL,
    address      TEXT,
    logo_path    TEXT
);

CREATE TABLE IF NOT EXISTS company_contacts (
    contact_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    INTEGER NOT NULL,
    contact_type  TEXT NOT NULL CHECK (contact_type IN ('phone','email','website')),
    contact_value TEXT NOT NULL,
    is_primary    INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
    FOREIGN KEY (company_id) REFERENCES company_info(company_id) ON DELETE CASCADE
);
/* one primary contact per company */
CREATE UNIQUE INDEX IF NOT EXISTS idx_company_contacts_one_primary
ON company_contacts(company_id) WHERE is_primary = 1;

/* -------- users -------- */
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    email           TEXT,
    role            TEXT NOT NULL DEFAULT 'user',
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_date    DATE DEFAULT CURRENT_DATE,
    last_login      TIMESTAMP,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

/* -------- parties -------- */
CREATE TABLE IF NOT EXISTS vendors (
    vendor_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    contact_info TEXT NOT NULL,
    address      TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    contact_info TEXT NOT NULL,
    address      TEXT,
    /* added via migration for old DBs; present by default for new DBs */
    is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1))
);

/* -------- expenses -------- */
CREATE TABLE IF NOT EXISTS expense_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
    expense_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT   NOT NULL,
    amount      NUMERIC NOT NULL CHECK (CAST(amount AS REAL) >= 0),
    date        DATE    NOT NULL DEFAULT CURRENT_DATE,
    category_id INTEGER,
    FOREIGN KEY (category_id) REFERENCES expense_categories(category_id)
);

/* -------- UoMs & products -------- */
CREATE TABLE IF NOT EXISTS uoms (
    uom_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    min_stock_level NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(min_stock_level AS REAL) >= 0)
);

CREATE TABLE IF NOT EXISTS product_uoms (
    product_uom_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id     INTEGER NOT NULL,
    uom_id         INTEGER NOT NULL,
    is_base        INTEGER NOT NULL DEFAULT 0 CHECK (is_base IN (0,1)),
    factor_to_base NUMERIC NOT NULL,
    UNIQUE(product_id, uom_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT,
    FOREIGN KEY (uom_id)     REFERENCES uoms(uom_id)
);
/* at most one base UoM per product */
CREATE UNIQUE INDEX IF NOT EXISTS idx_product_uoms_one_base
ON product_uoms(product_id) WHERE is_base = 1;

        -- (reverted) product_uom_roles removed; all UoMs are implicitly allowed for sales & purchases.

/* -------- docs: headers -------- */
CREATE TABLE IF NOT EXISTS purchases (
    purchase_id TEXT PRIMARY KEY,
    vendor_id   INTEGER NOT NULL,
    date        DATE    NOT NULL,
    total_amount  NUMERIC NOT NULL CHECK (CAST(total_amount AS REAL) >= 0),
    order_discount NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(order_discount AS REAL) >= 0),
    payment_status TEXT NOT NULL CHECK (payment_status IN ('paid','unpaid','partial')),
    paid_amount NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(paid_amount AS REAL) >= 0),
    advance_payment_applied NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(advance_payment_applied AS REAL) >= 0),
    notes       TEXT,
    created_by  INTEGER,
    FOREIGN KEY (vendor_id)  REFERENCES vendors(vendor_id),
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(date);

/* Unified: sales + quotations in one table via doc_type */
CREATE TABLE IF NOT EXISTS sales (
    sale_id     TEXT PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    date        DATE NOT NULL DEFAULT CURRENT_DATE,

    /* totals */
    total_amount NUMERIC NOT NULL CHECK (CAST(total_amount AS REAL) >= 0),
    order_discount NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(order_discount AS REAL) >= 0),

    /* payments (must remain zero & unpaid for quotations) */
    payment_status TEXT NOT NULL CHECK (payment_status IN ('paid','unpaid','partial')),
    paid_amount NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(paid_amount AS REAL) >= 0),
    advance_payment_applied NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(advance_payment_applied AS REAL) >= 0),

    notes       TEXT,
    created_by  INTEGER,
    source_type TEXT NOT NULL DEFAULT 'direct',
    source_id   INTEGER,

    /* quotation vs sale */
    doc_type    TEXT NOT NULL DEFAULT 'sale' CHECK (doc_type IN ('sale','quotation')),
    quotation_status TEXT CHECK (
        (doc_type='quotation' AND quotation_status IN ('draft','sent','accepted','expired','cancelled')) OR
        (doc_type='sale' AND quotation_status IS NULL)
    ),
    expiry_date DATE, -- optional for quotations

    /* ensure quotation rows don't show as paid/partial or carry paid amounts */
    CHECK (doc_type <> 'quotation' OR (
        payment_status = 'unpaid' AND
        CAST(paid_amount AS REAL) = 0 AND
        CAST(advance_payment_applied AS REAL) = 0
    )),

    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (created_by)  REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(date);
CREATE INDEX IF NOT EXISTS idx_sales_doc_type_date ON sales(doc_type, date);

-- (Removed separate quotations/quotation_items tables)

/* -------- line items (with UoM mapping checks) -------- */
CREATE TABLE IF NOT EXISTS purchase_items (
    item_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id    TEXT    NOT NULL,
    product_id     INTEGER NOT NULL,
    quantity       NUMERIC NOT NULL CHECK (CAST(quantity AS REAL) > 0),
    uom_id         INTEGER NOT NULL,
    purchase_price NUMERIC NOT NULL CHECK (CAST(purchase_price AS REAL) >= 0),
    sale_price     NUMERIC NOT NULL CHECK (CAST(sale_price AS REAL) >= 0),
    item_discount  NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(item_discount AS REAL) >= 0),
    FOREIGN KEY (purchase_id)            REFERENCES purchases(purchase_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id)             REFERENCES products(product_id),
    FOREIGN KEY (uom_id)                 REFERENCES uoms(uom_id),
    FOREIGN KEY (product_id, uom_id)     REFERENCES product_uoms(product_id, uom_id)
);
CREATE INDEX IF NOT EXISTS idx_purchase_items_purchase ON purchase_items(purchase_id);
CREATE INDEX IF NOT EXISTS idx_purchase_items_product  ON purchase_items(product_id);
CREATE INDEX IF NOT EXISTS idx_purchase_items_uom      ON purchase_items(uom_id);

CREATE TABLE IF NOT EXISTS sale_items (
    item_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id       TEXT    NOT NULL,  -- can belong to quotation or sale (doc_type controls behavior)
    product_id    INTEGER NOT NULL,
    quantity      NUMERIC NOT NULL CHECK (CAST(quantity AS REAL) > 0),
    uom_id        INTEGER NOT NULL,
    unit_price    NUMERIC NOT NULL CHECK (CAST(unit_price AS REAL) >= 0),
    item_discount NUMERIC NOT NULL DEFAULT 0 CHECK (CAST(item_discount AS REAL) >= 0),
    FOREIGN KEY (sale_id)                 REFERENCES sales(sale_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id)              REFERENCES products(product_id),
    FOREIGN KEY (uom_id)                  REFERENCES uoms(uom_id),
    FOREIGN KEY (product_id, uom_id)      REFERENCES product_uoms(product_id, uom_id)
);
CREATE INDEX IF NOT EXISTS idx_sale_items_sale    ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_product ON sale_items(product_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_uom     ON sale_items(uom_id);

/* -------- inventory ledger -------- */
CREATE TABLE IF NOT EXISTS inventory_transactions (
    transaction_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL,
    quantity         NUMERIC NOT NULL,  -- quantity in UoM of uom_id (positive expected; adjustments may be +/-)
    uom_id           INTEGER NOT NULL,
    transaction_type TEXT NOT NULL CHECK (transaction_type IN
         ('purchase','sale','sale_return','purchase_return','adjustment')),
    reference_table   TEXT,          -- 'purchases' or 'sales' or null for adjustments
    reference_id      TEXT,          -- purchase_id/sale_id (TEXT)
    reference_item_id INTEGER,       -- purchase_items.item_id / sale_items.item_id
    date              DATE NOT NULL, -- business date
    posted_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, -- for deterministic rebuild order
    txn_seq           INTEGER   NOT NULL DEFAULT 0,                 -- per-date sequence (set by app)
    notes             TEXT,
    created_by        INTEGER,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (uom_id)     REFERENCES uoms(uom_id),
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_inventory_product  ON inventory_transactions(product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_date     ON inventory_transactions(date);
CREATE INDEX IF NOT EXISTS idx_inventory_type     ON inventory_transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_it_product_order
  ON inventory_transactions(product_id, date, txn_seq, posted_at, transaction_id);

/* -------- stock valuation history (running average) -------- */
CREATE TABLE IF NOT EXISTS stock_valuation_history (
    valuation_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id       INTEGER NOT NULL,
    valuation_date   DATE    NOT NULL,
    quantity         NUMERIC NOT NULL,   -- on-hand qty in BASE UoM AFTER this txn
    unit_value       NUMERIC NOT NULL,   -- moving average unit cost (base)
    total_value      NUMERIC NOT NULL,
    valuation_method TEXT  NOT NULL,     -- 'moving_average'
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
CREATE INDEX IF NOT EXISTS idx_valuation_product_date
  ON stock_valuation_history(product_id, valuation_date);

/* -------- customer advances (credit ledger) -------- */
CREATE TABLE IF NOT EXISTS customer_advances (
    tx_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    tx_date     DATE    NOT NULL DEFAULT CURRENT_DATE,
    amount      NUMERIC NOT NULL,  -- +ve adds credit, -ve consumes credit
    source_type TEXT    NOT NULL CHECK (source_type IN ('deposit','applied_to_sale','return_credit')),
    source_id   TEXT,              -- e.g. sale_id
    notes       TEXT,
    created_by  INTEGER,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (created_by)  REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_cadv_cust    ON customer_advances(customer_id);
CREATE INDEX IF NOT EXISTS idx_cadv_cust_dt ON customer_advances(customer_id, tx_date);

/* -------- logs -------- */
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    action_type TEXT NOT NULL,
    table_name  TEXT,
    record_id   TEXT,
    action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details     TEXT,
    ip_address  TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS error_logs (
    error_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    error_time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error_type    TEXT NOT NULL,
    error_message TEXT NOT NULL,
    stack_trace   TEXT,
    context       TEXT,
    severity      TEXT NOT NULL CHECK (severity IN ('info','warn','error','fatal')),
    user_id       INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

/* === Company bank accounts === */
CREATE TABLE IF NOT EXISTS company_bank_accounts (
  account_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id   INTEGER NOT NULL DEFAULT 1,
  label        TEXT    NOT NULL,          -- "Meezan — Current"
  bank_name    TEXT,
  account_no   TEXT,
  iban         TEXT,
  routing_no   TEXT,
  is_active    INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  FOREIGN KEY (company_id) REFERENCES company_info(company_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_accounts_label
  ON company_bank_accounts(company_id, label);

/* === Payments per sale (supports partial, refunds, bank channel details) === */
CREATE TABLE IF NOT EXISTS sale_payments (
  payment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id         TEXT    NOT NULL,
  date            DATE    NOT NULL DEFAULT CURRENT_DATE,
  amount          NUMERIC NOT NULL,   -- +ve = payment, -ve = refund
  method          TEXT    NOT NULL CHECK (method IN ('Cash','Bank Transfer','Card','Cheque','Cash Deposit','Other')),
  bank_account_id INTEGER,
  instrument_type TEXT    CHECK (instrument_type IN ('online','cross_cheque','cash_deposit','pay_order','other')),
  instrument_no   TEXT,
  instrument_date DATE,
  deposited_date  DATE,
  cleared_date    DATE,
  clearing_state  TEXT    NOT NULL DEFAULT 'posted' CHECK (clearing_state IN ('posted','pending','cleared','bounced')),
  ref_no          TEXT,
  notes           TEXT,
  created_by      INTEGER,
  FOREIGN KEY (sale_id)         REFERENCES sales(sale_id) ON DELETE CASCADE,
  FOREIGN KEY (bank_account_id) REFERENCES company_bank_accounts(account_id),
  FOREIGN KEY (created_by)      REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_sale_payments_sale ON sale_payments(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_payments_date ON sale_payments(date);

/* === Payments per purchase (vendor) === */
CREATE TABLE IF NOT EXISTS purchase_payments (
  payment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  purchase_id     TEXT    NOT NULL,
  date            DATE    NOT NULL DEFAULT CURRENT_DATE,
  amount          NUMERIC NOT NULL,  -- +ve = payment to vendor, -ve = refund from vendor
  method          TEXT    NOT NULL CHECK (method IN ('Cash','Bank Transfer','Card','Cheque','Cross Cheque','Cash Deposit','Other')),
  bank_account_id INTEGER,
  vendor_bank_account_id INTEGER,
  instrument_type TEXT    CHECK (instrument_type IN ('online','cross_cheque','cash_deposit','pay_order','other','cheque')),
  instrument_no   TEXT,
  instrument_date DATE,
  deposited_date  DATE,
  cleared_date    DATE,
  clearing_state  TEXT    NOT NULL DEFAULT 'posted' CHECK (clearing_state IN ('posted','pending','cleared','bounced')),
  ref_no          TEXT,
  notes           TEXT,
  created_by      INTEGER,
  FOREIGN KEY (purchase_id)     REFERENCES purchases(purchase_id) ON DELETE CASCADE,
  FOREIGN KEY (bank_account_id) REFERENCES company_bank_accounts(account_id),
  FOREIGN KEY (vendor_bank_account_id) REFERENCES vendor_bank_accounts(vendor_bank_account_id),
  FOREIGN KEY (created_by)      REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_purchase_payments_purchase ON purchase_payments(purchase_id);
CREATE INDEX IF NOT EXISTS idx_purchase_payments_date     ON purchase_payments(date);
CREATE INDEX IF NOT EXISTS idx_purchase_payments_vendor_account
  ON purchase_payments(vendor_bank_account_id);

/* === Vendor bank accounts (destination) === */
CREATE TABLE IF NOT EXISTS vendor_bank_accounts (
  vendor_bank_account_id INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_id              INTEGER NOT NULL,
  label                  TEXT    NOT NULL,   -- "HBL — Current"
  bank_name              TEXT,
  account_no             TEXT,
  iban                   TEXT,
  routing_no             TEXT,
  is_primary             INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
  is_active              INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
  FOREIGN KEY (vendor_id) REFERENCES vendors(vendor_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vba_label
  ON vendor_bank_accounts(vendor_id, label);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vba_one_primary
  ON vendor_bank_accounts(vendor_id)
  WHERE is_primary = 1;
CREATE INDEX IF NOT EXISTS idx_vba_vendor_active
  ON vendor_bank_accounts(vendor_id, is_active);

/* ======================== BACK-DATED REBUILD SUPPORT (Option 2) ======================== */
CREATE TABLE IF NOT EXISTS valuation_dirty (
  product_id        INTEGER PRIMARY KEY,
  earliest_impacted DATE     NOT NULL,
  reason            TEXT,
  updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

/* === Vendor advances / credits === */
CREATE TABLE IF NOT EXISTS vendor_advances (
  tx_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  vendor_id   INTEGER NOT NULL,
  tx_date     DATE    NOT NULL DEFAULT CURRENT_DATE,
  amount      NUMERIC NOT NULL,  -- +ve = credit granted, -ve = credit applied
  source_type TEXT    NOT NULL CHECK (source_type IN ('deposit','applied_to_purchase','return_credit')),
  source_id   TEXT,              -- e.g., purchase_id (for application), or return ref
  notes       TEXT,
  created_by  INTEGER,
  FOREIGN KEY (vendor_id)  REFERENCES vendors(vendor_id),
  FOREIGN KEY (created_by) REFERENCES users(user_id)
);
CREATE INDEX IF NOT EXISTS idx_vadv_vendor     ON vendor_advances(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vadv_vendor_dt  ON vendor_advances(vendor_id, tx_date);
CREATE INDEX IF NOT EXISTS idx_vadv_source     ON vendor_advances(source_id);

/* -------- customers: indexes to speed list/search -------- */

/* 1) Cover the common list view: WHERE is_active=1 ORDER BY customer_id DESC */
CREATE INDEX IF NOT EXISTS idx_customers_active_id
  ON customers(is_active, customer_id DESC);

/* 2) Columns used by LIKE in search() */
CREATE INDEX IF NOT EXISTS idx_customers_name
  ON customers(name);

CREATE INDEX IF NOT EXISTS idx_customers_contact_info
  ON customers(contact_info);

CREATE INDEX IF NOT EXISTS idx_customers_address
  ON customers(address);

/* 3) If you keep CAST(customer_id AS TEXT) in LIKE, an expression index helps for prefix matches */
CREATE INDEX IF NOT EXISTS idx_customers_id_text
  ON customers( CAST(customer_id AS TEXT) );



/* ======================== UoM INTEGRITY TRIGGERS ======================== */
DROP TRIGGER IF EXISTS trg_product_uoms_factor_guard_ins;
DROP TRIGGER IF EXISTS trg_product_uoms_factor_guard_upd;

CREATE TRIGGER trg_product_uoms_factor_guard_ins
BEFORE INSERT ON product_uoms
FOR EACH ROW
BEGIN
  SELECT CASE
    WHEN NEW.is_base = 1 AND CAST(NEW.factor_to_base AS REAL) = 1 THEN 1
    WHEN NEW.is_base = 0 AND CAST(NEW.factor_to_base AS REAL) > 0 THEN 1
    ELSE RAISE(ABORT, 'Invalid factor_to_base for base/non-base UoM')
  END;
END;



CREATE TRIGGER trg_product_uoms_factor_guard_upd
BEFORE UPDATE ON product_uoms
FOR EACH ROW
BEGIN
  SELECT CASE
    WHEN NEW.is_base = 1 AND CAST(NEW.factor_to_base AS REAL) = 1 THEN 1
    WHEN NEW.is_base = 0 AND CAST(NEW.factor_to_base AS REAL) > 0 THEN 1
    ELSE RAISE(ABORT, 'Invalid factor_to_base for base/non-base UoM')
  END;
END;

/* === UoM CHANGE LOCKS (once used) === */
DROP TRIGGER IF EXISTS trg_lock_uom_factor_after_activity;
CREATE TRIGGER trg_lock_uom_factor_after_activity
BEFORE UPDATE OF factor_to_base ON product_uoms
FOR EACH ROW
WHEN EXISTS (
  SELECT 1 FROM inventory_transactions it
  WHERE it.product_id = NEW.product_id
    AND it.uom_id     = NEW.uom_id
)
BEGIN
  SELECT RAISE(ABORT, 'Cannot change factor_to_base once transactions exist for this product/UoM');
END;

DROP TRIGGER IF EXISTS trg_block_delete_used_uom_map;
CREATE TRIGGER trg_block_delete_used_uom_map
BEFORE DELETE ON product_uoms
FOR EACH ROW
WHEN EXISTS (
  SELECT 1 FROM inventory_transactions it
  WHERE it.product_id = OLD.product_id
    AND it.uom_id     = OLD.uom_id
)
BEGIN
  SELECT RAISE(ABORT, 'Cannot delete UoM mapping referenced by transactions');
END;

DROP TRIGGER IF EXISTS trg_lock_base_uom_after_activity;
CREATE TRIGGER trg_lock_base_uom_after_activity
BEFORE UPDATE OF is_base ON product_uoms
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM inventory_transactions it WHERE it.product_id = NEW.product_id)
BEGIN
  SELECT RAISE(ABORT, 'Cannot change base UoM once the product has transactions');
END;

/* ======================== PURCHASE BASE-UOM ENFORCEMENT ======================== */
DROP TRIGGER IF EXISTS trg_purchase_items_base_only_ins;
DROP TRIGGER IF EXISTS trg_purchase_items_base_only_upd;

CREATE TRIGGER trg_purchase_items_base_only_ins
BEFORE INSERT ON purchase_items
FOR EACH ROW
BEGIN
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM product_uoms
      WHERE product_id = NEW.product_id
        AND uom_id     = NEW.uom_id
        AND is_base    = 1
    )
    THEN 1
    ELSE RAISE(ABORT, 'Purchases must use the product base UoM')
  END;
END;

CREATE TRIGGER trg_purchase_items_base_only_upd
BEFORE UPDATE ON purchase_items
FOR EACH ROW
BEGIN
  SELECT CASE
    WHEN EXISTS (
      SELECT 1 FROM product_uoms
      WHERE product_id = NEW.product_id
        AND uom_id     = NEW.uom_id
        AND is_base    = 1
    )
    THEN 1
    ELSE RAISE(ABORT, 'Purchases must use the product base UoM')
  END;
END;

/* ======================== INVENTORY VALIDATION TRIGGERS ======================== */
DROP TRIGGER IF EXISTS trg_inventory_ref_validate;
CREATE TRIGGER trg_inventory_ref_validate
BEFORE INSERT ON inventory_transactions
FOR EACH ROW
BEGIN
  -- require a defined product/uom mapping
  SELECT CASE
    WHEN NOT EXISTS (
      SELECT 1 FROM product_uoms pu
      WHERE pu.product_id = NEW.product_id
        AND pu.uom_id     = NEW.uom_id
    )
    THEN RAISE(ABORT, 'Unknown product/UoM mapping for inventory')
    ELSE 1
  END;

  -- basic non-negativity hint (allow negative only for adjustments)
  SELECT CASE
    WHEN NEW.transaction_type <> 'adjustment' AND CAST(NEW.quantity AS REAL) <= 0
      THEN RAISE(ABORT, 'Quantity must be > 0 (except adjustments)')
    ELSE 1 END;

  -- ensure referenced rows exist + correct table
  SELECT CASE
    WHEN NEW.transaction_type = 'purchase' AND (
         NEW.reference_table <> 'purchases'
      OR NOT EXISTS (SELECT 1 FROM purchase_items pi WHERE pi.item_id = NEW.reference_item_id)
    )
      THEN RAISE(ABORT, 'Purchase inventory must reference purchase_items')

    WHEN NEW.transaction_type = 'purchase_return' AND (
         NEW.reference_table <> 'purchases'
      OR NEW.reference_item_id IS NULL
      OR NOT EXISTS (SELECT 1 FROM purchase_items pi WHERE pi.item_id = NEW.reference_item_id)
    )
      THEN RAISE(ABORT, 'Purchase return must reference a purchase item')

    WHEN NEW.transaction_type IN ('sale','sale_return') AND (
         NEW.reference_table <> 'sales'
      OR NOT EXISTS (SELECT 1 FROM sale_items si WHERE si.item_id = NEW.reference_item_id)
    )
      THEN RAISE(ABORT, 'Sale inventory must reference sale_items')
    ELSE 1 END;

  -- product/uom must match referenced item
  SELECT CASE
    WHEN NEW.transaction_type = 'purchase' AND EXISTS (
         SELECT 1
         FROM purchase_items pi
         WHERE pi.item_id = NEW.reference_item_id
           AND (pi.product_id <> NEW.product_id OR pi.uom_id <> NEW.uom_id)
    ) THEN RAISE(ABORT, 'Inventory row product/uom must match purchase item')

    WHEN NEW.transaction_type IN ('sale','sale_return') AND EXISTS (
         SELECT 1
         FROM sale_items si
         WHERE si.item_id = NEW.reference_item_id
           AND (si.product_id <> NEW.product_id OR si.uom_id <> NEW.uom_id)
    ) THEN RAISE(ABORT, 'Inventory row product/uom must match sale item')
    ELSE 1 END;

  -- header/item coherence AND sales must be real 'sale' (not quotation)
  SELECT CASE
    WHEN NEW.transaction_type IN ('purchase','purchase_return') AND NOT EXISTS (
         SELECT 1 FROM purchase_items pi
         WHERE pi.item_id = NEW.reference_item_id
           AND pi.purchase_id = NEW.reference_id
    ) THEN RAISE(ABORT, 'Inventory ref_id does not match purchase item/header')

    WHEN NEW.transaction_type IN ('sale','sale_return') AND NOT EXISTS (
         SELECT 1
         FROM sale_items si
         JOIN sales s ON s.sale_id = si.sale_id AND s.doc_type = 'sale'
         WHERE si.item_id = NEW.reference_item_id
           AND s.sale_id  = NEW.reference_id
    ) THEN RAISE(ABORT, 'Inventory must reference a SALE (doc_type=sale), not a quotation')

    ELSE 1 END;
END;

/* Block converting a posted sale back to quotation */
DROP TRIGGER IF EXISTS trg_sales_doc_type_guard;
CREATE TRIGGER trg_sales_doc_type_guard
BEFORE UPDATE OF doc_type ON sales
FOR EACH ROW
WHEN OLD.doc_type = 'sale' AND NEW.doc_type = 'quotation'
BEGIN
  SELECT RAISE(ABORT, 'Cannot convert a posted sale back to quotation');
END;

/* Disallow payments against quotations */
DROP TRIGGER IF EXISTS trg_disallow_payments_on_quotations_ins;
CREATE TRIGGER trg_disallow_payments_on_quotations_ins
BEFORE INSERT ON sale_payments
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM sales s WHERE s.sale_id = NEW.sale_id AND s.doc_type = 'quotation')
BEGIN
  SELECT RAISE(ABORT, 'Payments cannot be recorded against quotations');
END;

DROP TRIGGER IF EXISTS trg_disallow_payments_on_quotations_upd;
CREATE TRIGGER trg_disallow_payments_on_quotations_upd
BEFORE UPDATE OF sale_id ON sale_payments
FOR EACH ROW
WHEN EXISTS (SELECT 1 FROM sales s WHERE s.sale_id = NEW.sale_id AND s.doc_type = 'quotation')
BEGIN
  SELECT RAISE(ABORT, 'Payments cannot be recorded against quotations');
END;

/* ======================== MOVING-AVERAGE COSTING TRIGGER ======================== */
DROP TRIGGER IF EXISTS trg_stock_valuation_after_transaction;
CREATE TRIGGER trg_stock_valuation_after_transaction
AFTER INSERT ON inventory_transactions
FOR EACH ROW
BEGIN
  INSERT INTO stock_valuation_history
    (product_id, valuation_date, quantity, unit_value, total_value, valuation_method)
  SELECT
    NEW.product_id,
    NEW.date,

    /* quantity in base UoM after this txn */
    CASE
      WHEN NEW.transaction_type IN ('purchase','sale_return','adjustment') THEN
        COALESCE((
          SELECT svh.quantity
          FROM stock_valuation_history svh
          WHERE svh.product_id = NEW.product_id
            AND DATE(svh.valuation_date) <= DATE(NEW.date)
          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
          LIMIT 1
        ), 0.0)
        + (CAST(NEW.quantity AS REAL) * COALESCE((
            SELECT CAST(pu.factor_to_base AS REAL)
            FROM product_uoms pu
            WHERE pu.product_id = NEW.product_id
              AND pu.uom_id     = NEW.uom_id
            LIMIT 1
          ), 1.0))
      WHEN NEW.transaction_type IN ('sale','purchase_return') THEN
        COALESCE((
          SELECT svh.quantity
          FROM stock_valuation_history svh
          WHERE svh.product_id = NEW.product_id
            AND DATE(svh.valuation_date) <= DATE(NEW.date)
          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
          LIMIT 1
        ), 0.0)
        - (CAST(NEW.quantity AS REAL) * COALESCE((
            SELECT CAST(pu.factor_to_base AS REAL)
            FROM product_uoms pu
            WHERE pu.product_id = NEW.product_id
              AND pu.uom_id     = NEW.uom_id
            LIMIT 1
          ), 1.0))
      ELSE
        COALESCE((
          SELECT svh.quantity
          FROM stock_valuation_history svh
          WHERE svh.product_id = NEW.product_id
            AND DATE(svh.valuation_date) <= DATE(NEW.date)
          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
          LIMIT 1
        ), 0.0)
    END AS qty_new,

    /* unit cost (moving average) */
    CASE
      WHEN NEW.transaction_type = 'purchase' THEN
        CASE
          WHEN (
            COALESCE((
              SELECT svh.quantity
              FROM stock_valuation_history svh
              WHERE svh.product_id = NEW.product_id
                AND DATE(svh.valuation_date) <= DATE(NEW.date)
              ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
              LIMIT 1
            ), 0.0)
            +
            (CAST(NEW.quantity AS REAL) * COALESCE((
              SELECT CAST(pu.factor_to_base AS REAL)
              FROM product_uoms pu
              WHERE pu.product_id = NEW.product_id
                AND pu.uom_id     = NEW.uom_id
              LIMIT 1
            ), 1.0))
          ) > 0
          THEN (
            (
              COALESCE((
                SELECT svh.quantity
                FROM stock_valuation_history svh
                WHERE svh.product_id = NEW.product_id
                  AND DATE(svh.valuation_date) <= DATE(NEW.date)
                ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                LIMIT 1
              ), 0.0)
              *
              COALESCE((
                SELECT svh.unit_value
                FROM stock_valuation_history svh
                WHERE svh.product_id = NEW.product_id
                  AND DATE(svh.valuation_date) <= DATE(NEW.date)
                ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                LIMIT 1
              ), 0.0)
            )
            +
            (
              (CAST(NEW.quantity AS REAL) * COALESCE((
                SELECT CAST(pu.factor_to_base AS REAL)
                FROM product_uoms pu
                WHERE pu.product_id = NEW.product_id
                  AND pu.uom_id     = NEW.uom_id
                LIMIT 1
              ), 1.0))
              *
              COALESCE((
                SELECT (
                         CAST(pi.purchase_price AS REAL)
                         - COALESCE(CAST(pi.item_discount AS REAL), 0.0)
                       )
                       /
                       COALESCE((
                         SELECT CAST(pu.factor_to_base AS REAL)
                         FROM product_uoms pu
                         WHERE pu.product_id = pi.product_id
                           AND pu.uom_id     = pi.uom_id
                         LIMIT 1
                       ), 1.0)
                FROM purchase_items pi
                WHERE pi.item_id = NEW.reference_item_id
              ), 0.0)
            )
          )
          /
          (
            COALESCE((
              SELECT svh.quantity
              FROM stock_valuation_history svh
              WHERE svh.product_id = NEW.product_id
                AND DATE(svh.valuation_date) <= DATE(NEW.date)
              ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
              LIMIT 1
            ), 0.0)
            +
            (CAST(NEW.quantity AS REAL) * COALESCE((
              SELECT CAST(pu.factor_to_base AS REAL)
              FROM product_uoms pu
              WHERE pu.product_id = NEW.product_id
                AND pu.uom_id     = NEW.uom_id
              LIMIT 1
            ), 1.0))
          )
          ELSE
            COALESCE((
              SELECT (
                       CAST(pi.purchase_price AS REAL)
                       - COALESCE(CAST(pi.item_discount AS REAL), 0.0)
                     )
                     /
                     COALESCE((
                       SELECT CAST(pu.factor_to_base AS REAL)
                       FROM product_uoms pu
                       WHERE pu.product_id = pi.product_id
                         AND pu.uom_id     = pi.uom_id
                       LIMIT 1
                     ), 1.0)
              FROM purchase_items pi
              WHERE pi.item_id = NEW.reference_item_id
            ),
            COALESCE((
              SELECT svh.unit_value
              FROM stock_valuation_history svh
              WHERE svh.product_id = NEW.product_id
                AND DATE(svh.valuation_date) <= DATE(NEW.date)
              ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
              LIMIT 1
            ), 0.0))
        END
      ELSE
        COALESCE((
          SELECT svh.unit_value
          FROM stock_valuation_history svh
          WHERE svh.product_id = NEW.product_id
            AND DATE(svh.valuation_date) <= DATE(NEW.date)
          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
          LIMIT 1
        ), 0.0)
    END AS uc_new,

    /* total value after txn (uc * qty_new) */
    CASE
      WHEN NEW.transaction_type IN ('purchase','sale_return','adjustment') THEN
        (
          CASE
            WHEN (
              COALESCE((
                SELECT svh.quantity
                FROM stock_valuation_history svh
                WHERE svh.product_id = NEW.product_id
                  AND DATE(svh.valuation_date) <= DATE(NEW.date)
                ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                LIMIT 1
              ), 0.0)
              +
              (CAST(NEW.quantity AS REAL) * COALESCE((
                SELECT CAST(pu.factor_to_base AS REAL)
                FROM product_uoms pu
                WHERE pu.product_id = NEW.product_id
                  AND pu.uom_id     = NEW.uom_id
                LIMIT 1
              ), 1.0))
            ) > 0
            THEN
              (
                CASE
                  WHEN NEW.transaction_type = 'purchase' THEN
                    (
                      (
                        COALESCE((
                          SELECT svh.quantity
                          FROM stock_valuation_history svh
                          WHERE svh.product_id = NEW.product_id
                            AND DATE(svh.valuation_date) <= DATE(NEW.date)
                          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                          LIMIT 1
                        ), 0.0)
                        *
                        COALESCE((
                          SELECT svh.unit_value
                          FROM stock_valuation_history svh
                          WHERE svh.product_id = NEW.product_id
                            AND DATE(svh.valuation_date) <= DATE(NEW.date)
                          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                          LIMIT 1
                        ), 0.0)
                      )
                      +
                      (
                        (CAST(NEW.quantity AS REAL) * COALESCE((
                          SELECT CAST(pu.factor_to_base AS REAL)
                          FROM product_uoms pu
                          WHERE pu.product_id = NEW.product_id
                            AND pu.uom_id     = NEW.uom_id
                          LIMIT 1
                        ), 1.0))
                        *
                        COALESCE((
                          SELECT (
                                   CAST(pi.purchase_price AS REAL)
                                   - COALESCE(CAST(pi.item_discount AS REAL), 0.0)
                                 )
                                 /
                                 COALESCE((
                                   SELECT CAST(pu.factor_to_base AS REAL)
                                   FROM product_uoms pu
                                   WHERE pu.product_id = pi.product_id
                                     AND pu.uom_id     = pi.uom_id
                                   LIMIT 1
                                 ), 1.0)
                          FROM purchase_items pi
                          WHERE pi.item_id = NEW.reference_item_id
                        ), 0.0)
                      )
                    )
                    /
                    (
                      COALESCE((
                        SELECT svh.quantity
                        FROM stock_valuation_history svh
                        WHERE svh.product_id = NEW.product_id
                          AND DATE(svh.valuation_date) <= DATE(NEW.date)
                        ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                        LIMIT 1
                      ), 0.0)
                      +
                      (CAST(NEW.quantity AS REAL) * COALESCE((
                        SELECT CAST(pu.factor_to_base AS REAL)
                        FROM product_uoms pu
                        WHERE pu.product_id = NEW.product_id
                          AND pu.uom_id     = NEW.uom_id
                        LIMIT 1
                      ), 1.0))
                    )
                  ELSE
                    COALESCE((
                      SELECT svh.unit_value
                      FROM stock_valuation_history svh
                      WHERE svh.product_id = NEW.product_id
                        AND DATE(svh.valuation_date) <= DATE(NEW.date)
                      ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                      LIMIT 1
                    ), 0.0)
                END
              )
              *
              (
                COALESCE((
                  SELECT svh.quantity
                  FROM stock_valuation_history svh
                  WHERE svh.product_id = NEW.product_id
                    AND DATE(svh.valuation_date) <= DATE(NEW.date)
                  ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
                  LIMIT 1
                ), 0.0)
                +
                (CAST(NEW.quantity AS REAL) * COALESCE((
                  SELECT CAST(pu.factor_to_base AS REAL)
                  FROM product_uoms pu
                  WHERE pu.product_id = NEW.product_id
                    AND pu.uom_id     = NEW.uom_id
                  LIMIT 1
                ), 1.0))
              )
            ELSE 0.0
          END
        )
      WHEN NEW.transaction_type IN ('sale','purchase_return') THEN
        COALESCE((
          SELECT svh.unit_value
          FROM stock_valuation_history svh
          WHERE svh.product_id = NEW.product_id
            AND DATE(svh.valuation_date) <= DATE(NEW.date)
          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
          LIMIT 1
        ), 0.0)
        *
        (
          COALESCE((
            SELECT svh.quantity
            FROM stock_valuation_history svh
            WHERE svh.product_id = NEW.product_id
              AND DATE(svh.valuation_date) <= DATE(NEW.date)
            ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
            LIMIT 1
          ), 0.0)
          -
          (CAST(NEW.quantity AS REAL) * COALESCE((
            SELECT CAST(pu.factor_to_base AS REAL)
            FROM product_uoms pu
            WHERE pu.product_id = NEW.product_id
              AND pu.uom_id     = NEW.uom_id
            LIMIT 1
          ), 1.0))
        )
      ELSE
        COALESCE((
          SELECT svh.unit_value
          FROM stock_valuation_history svh
          WHERE svh.product_id = NEW.product_id
            AND DATE(svh.valuation_date) <= DATE(NEW.date)
          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
          LIMIT 1
        ), 0.0)
        *
        COALESCE((
          SELECT svh.quantity
          FROM stock_valuation_history svh
          WHERE svh.product_id = NEW.product_id
            AND DATE(svh.valuation_date) <= DATE(NEW.date)
          ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
          LIMIT 1
        ), 0.0)
    END AS total_value_new,

    'moving_average';
END;



DROP TRIGGER IF EXISTS trg_mark_dirty_on_backdate_ins;
CREATE TRIGGER trg_mark_dirty_on_backdate_ins
AFTER INSERT ON inventory_transactions
FOR EACH ROW
WHEN EXISTS (
  SELECT 1 FROM stock_valuation_history svh
  WHERE svh.product_id = NEW.product_id
    AND DATE(svh.valuation_date) > DATE(NEW.date)
)
BEGIN
  INSERT INTO valuation_dirty (product_id, earliest_impacted, reason, updated_at)
  VALUES (NEW.product_id, NEW.date, 'inventory_insert_backdate', CURRENT_TIMESTAMP)
  ON CONFLICT(product_id) DO UPDATE SET
    earliest_impacted = MIN(valuation_dirty.earliest_impacted, excluded.earliest_impacted),
    reason            = COALESCE(valuation_dirty.reason, excluded.reason),
    updated_at        = CURRENT_TIMESTAMP;
END;

DROP TRIGGER IF EXISTS trg_mark_dirty_on_inventory_upd;
CREATE TRIGGER trg_mark_dirty_on_inventory_upd
AFTER UPDATE OF date, quantity, uom_id, transaction_type, reference_item_id ON inventory_transactions
FOR EACH ROW
BEGIN
  INSERT INTO valuation_dirty (product_id, earliest_impacted, reason, updated_at)
  VALUES (NEW.product_id, MIN(NEW.date, OLD.date), 'inventory_update', CURRENT_TIMESTAMP)
  ON CONFLICT(product_id) DO UPDATE SET
    earliest_impacted = MIN(valuation_dirty.earliest_impacted, excluded.earliest_impacted),
    reason            = COALESCE(valuation_dirty.reason, excluded.reason),
    updated_at        = CURRENT_TIMESTAMP;
END;

DROP TRIGGER IF EXISTS trg_mark_dirty_on_inventory_del;
CREATE TRIGGER trg_mark_dirty_on_inventory_del
AFTER DELETE ON inventory_transactions
FOR EACH ROW
BEGIN
  INSERT INTO valuation_dirty (product_id, earliest_impacted, reason, updated_at)
  VALUES (OLD.product_id, OLD.date, 'inventory_delete', CURRENT_TIMESTAMP)
  ON CONFLICT(product_id) DO UPDATE SET
    earliest_impacted = MIN(valuation_dirty.earliest_impacted, excluded.earliest_impacted),
    reason            = COALESCE(valuation_dirty.reason, excluded.reason),
    updated_at        = CURRENT_TIMESTAMP;
END;

DROP TRIGGER IF EXISTS trg_mark_dirty_on_purchase_item_price_change;
CREATE TRIGGER trg_mark_dirty_on_purchase_item_price_change
AFTER UPDATE OF purchase_price, item_discount, uom_id ON purchase_items
FOR EACH ROW
BEGIN
  INSERT INTO valuation_dirty (product_id, earliest_impacted, reason, updated_at)
  VALUES (
    NEW.product_id,
    (SELECT p.date FROM purchases p WHERE p.purchase_id = NEW.purchase_id),
    'purchase_price_change',
    CURRENT_TIMESTAMP
  )
  ON CONFLICT(product_id) DO UPDATE SET
    earliest_impacted = MIN(valuation_dirty.earliest_impacted, excluded.earliest_impacted),
    reason            = COALESCE(valuation_dirty.reason, excluded.reason),
    updated_at        = CURRENT_TIMESTAMP;
END;

/* ======================== CREDIT / PAYMENT TRIGGERS ======================== */

/* Guard: don’t allow applying more credit than available */
DROP TRIGGER IF EXISTS trg_advances_no_overdraw;
CREATE TRIGGER trg_advances_no_overdraw
BEFORE INSERT ON customer_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_sale'
BEGIN
  SELECT CASE
    WHEN (
      COALESCE((SELECT SUM(CAST(amount AS REAL))
                FROM customer_advances
                WHERE customer_id = NEW.customer_id), 0.0)
      + CAST(NEW.amount AS REAL)  -- NEW.amount negative when applying
    ) < -1e-9
    THEN RAISE(ABORT, 'Insufficient customer credit')
    ELSE 1
  END;
END;

/* New guard: do not allow applying credit beyond a sale's remaining due */
DROP TRIGGER IF EXISTS trg_customer_advances_not_exceed_remaining_due;
CREATE TRIGGER trg_customer_advances_not_exceed_remaining_due
BEFORE INSERT ON customer_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_sale' AND NEW.source_id IS NOT NULL
BEGIN
  /* Ensure referenced sale exists */
  SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM sales s WHERE s.sale_id = NEW.source_id)
      THEN RAISE(ABORT, 'Invalid sale reference for customer credit application')
    ELSE 1
  END;

  /* remaining_due = total_amount - paid_amount - advance_payment_applied */
  SELECT CASE
    WHEN (
      COALESCE((SELECT CAST(total_amount AS REAL)            FROM sales WHERE sale_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(paid_amount AS REAL)             FROM sales WHERE sale_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(advance_payment_applied AS REAL) FROM sales WHERE sale_id = NEW.source_id), 0.0)
      + CAST(NEW.amount AS REAL)  /* NEW.amount negative when applying */
    ) < -1e-9
    THEN RAISE(ABORT, 'Cannot apply credit beyond remaining due')
    ELSE 1
  END;
END;

/* Roll up paid_amount & payment_status from sale_payments (clamped ≥ 0) */
DROP TRIGGER IF EXISTS trg_paid_from_sale_payments_ai;
DROP TRIGGER IF EXISTS trg_paid_from_sale_payments_au;
DROP TRIGGER IF EXISTS trg_paid_from_sale_payments_ad;

CREATE TRIGGER trg_paid_from_sale_payments_ai
AFTER INSERT ON sale_payments
FOR EACH ROW
BEGIN
  UPDATE sales
     SET paid_amount = MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = NEW.sale_id), 0.0)),
         payment_status = CASE
            WHEN MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = NEW.sale_id),0.0)) >= CAST(total_amount AS REAL) THEN 'paid'
            WHEN MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = NEW.sale_id),0.0)) > 0 THEN 'partial'
            ELSE 'unpaid' END
   WHERE sale_id = NEW.sale_id;
END;

CREATE TRIGGER trg_paid_from_sale_payments_au
AFTER UPDATE ON sale_payments
FOR EACH ROW
BEGIN
  UPDATE sales
     SET paid_amount = MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = NEW.sale_id), 0.0)),
         payment_status = CASE
            WHEN MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = NEW.sale_id),0.0)) >= CAST(total_amount AS REAL) THEN 'paid'
            WHEN MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = NEW.sale_id),0.0)) > 0 THEN 'partial'
            ELSE 'unpaid' END
   WHERE sale_id = NEW.sale_id;
END;

CREATE TRIGGER trg_paid_from_sale_payments_ad
AFTER DELETE ON sale_payments
FOR EACH ROW
BEGIN
  UPDATE sales
     SET paid_amount = MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = OLD.sale_id), 0.0)),
         payment_status = CASE
            WHEN MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = OLD.sale_id),0.0)) >= CAST(total_amount AS REAL) THEN 'paid'
            WHEN MAX(0.0, COALESCE((SELECT SUM(CAST(amount AS REAL)) FROM sale_payments WHERE sale_id = OLD.sale_id),0.0)) > 0 THEN 'partial'
            ELSE 'unpaid' END
   WHERE sale_id = OLD.sale_id;
END;

/* Roll up sales.advance_payment_applied from customer credit applications */
DROP TRIGGER IF EXISTS trg_adv_applied_from_customer_ai;
DROP TRIGGER IF EXISTS trg_adv_applied_from_customer_au;
DROP TRIGGER IF EXISTS trg_adv_applied_from_customer_ad;

CREATE TRIGGER trg_adv_applied_from_customer_ai
AFTER INSERT ON customer_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_sale' AND NEW.source_id IS NOT NULL
BEGIN
  UPDATE sales
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM customer_advances ca
           WHERE ca.source_type = 'applied_to_sale'
             AND ca.source_id   = NEW.source_id
         ), 0.0))
   WHERE sale_id = NEW.source_id;
END;

CREATE TRIGGER trg_adv_applied_from_customer_au
AFTER UPDATE ON customer_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_sale' AND NEW.source_id IS NOT NULL
BEGIN
  UPDATE sales
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM customer_advances ca
           WHERE ca.source_type = 'applied_to_sale'
             AND ca.source_id   = NEW.source_id
         ), 0.0))
   WHERE sale_id = NEW.source_id;
END;

CREATE TRIGGER trg_adv_applied_from_customer_ad
AFTER DELETE ON customer_advances
FOR EACH ROW
WHEN OLD.source_type = 'applied_to_sale' AND OLD.source_id IS NOT NULL
BEGIN
  UPDATE sales
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM customer_advances ca
           WHERE ca.source_type = 'applied_to_sale'
             AND ca.source_id   = OLD.source_id
         ), 0.0))
   WHERE sale_id = OLD.source_id;
END;

/* Roll up paid_amount & payment_status from purchase_payments (clamped ≥ 0; cleared only) */
DROP TRIGGER IF EXISTS trg_paid_from_purchase_payments_ai;
DROP TRIGGER IF EXISTS trg_paid_from_purchase_payments_au;
DROP TRIGGER IF EXISTS trg_paid_from_purchase_payments_ad;

CREATE TRIGGER trg_paid_from_purchase_payments_ai
AFTER INSERT ON purchase_payments
FOR EACH ROW
BEGIN
  UPDATE purchases
     SET paid_amount = MAX(
           0.0,
           COALESCE((
             SELECT SUM(CAST(amount AS REAL))
             FROM purchase_payments
             WHERE purchase_id = NEW.purchase_id
               AND clearing_state = 'cleared'
           ), 0.0)
         ),
         payment_status = CASE
            WHEN MAX(0.0, COALESCE((
                 SELECT SUM(CAST(amount AS REAL))
                 FROM purchase_payments
                 WHERE purchase_id = NEW.purchase_id
                   AND clearing_state = 'cleared'
               ), 0.0)) >= CAST(total_amount AS REAL) THEN 'paid'
            WHEN MAX(0.0, COALESCE((
                 SELECT SUM(CAST(amount AS REAL))
                 FROM purchase_payments
                 WHERE purchase_id = NEW.purchase_id
                   AND clearing_state = 'cleared'
               ), 0.0)) > 0 THEN 'partial'
            ELSE 'unpaid' END
   WHERE purchase_id = NEW.purchase_id;
END;

CREATE TRIGGER trg_paid_from_purchase_payments_au
AFTER UPDATE ON purchase_payments
FOR EACH ROW
BEGIN
  UPDATE purchases
     SET paid_amount = MAX(
           0.0,
           COALESCE((
             SELECT SUM(CAST(amount AS REAL))
             FROM purchase_payments
             WHERE purchase_id = NEW.purchase_id
               AND clearing_state = 'cleared'
           ), 0.0)
         ),
         payment_status = CASE
            WHEN MAX(0.0, COALESCE((
                 SELECT SUM(CAST(amount AS REAL))
                 FROM purchase_payments
                 WHERE purchase_id = NEW.purchase_id
                   AND clearing_state = 'cleared'
               ), 0.0)) >= CAST(total_amount AS REAL) THEN 'paid'
            WHEN MAX(0.0, COALESCE((
                 SELECT SUM(CAST(amount AS REAL))
                 FROM purchase_payments
                 WHERE purchase_id = NEW.purchase_id
                   AND clearing_state = 'cleared'
               ), 0.0)) > 0 THEN 'partial'
            ELSE 'unpaid' END
   WHERE purchase_id = NEW.purchase_id;
END;

CREATE TRIGGER trg_paid_from_purchase_payments_ad
AFTER DELETE ON purchase_payments
FOR EACH ROW
BEGIN
  UPDATE purchases
     SET paid_amount = MAX(
           0.0,
           COALESCE((
             SELECT SUM(CAST(amount AS REAL))
             FROM purchase_payments
             WHERE purchase_id = OLD.purchase_id
               AND clearing_state = 'cleared'
           ), 0.0)
         ),
         payment_status = CASE
            WHEN MAX(0.0, COALESCE((
                 SELECT SUM(CAST(amount AS REAL))
                 FROM purchase_payments
                 WHERE purchase_id = OLD.purchase_id
                   AND clearing_state = 'cleared'
               ), 0.0)) >= CAST(total_amount AS REAL) THEN 'paid'
            WHEN MAX(0.0, COALESCE((
                 SELECT SUM(CAST(amount AS REAL))
                 FROM purchase_payments
                 WHERE purchase_id = OLD.purchase_id
                   AND clearing_state = 'cleared'
               ), 0.0)) > 0 THEN 'partial'
            ELSE 'unpaid' END
   WHERE purchase_id = OLD.purchase_id;
END;


/* Enforce method-specific requirements on purchase_payments */
DROP TRIGGER IF EXISTS trg_pp_method_checks_ins;
DROP TRIGGER IF EXISTS trg_pp_method_checks_upd;

DROP TRIGGER IF EXISTS trg_pp_method_checks_ins;
CREATE TRIGGER trg_pp_method_checks_ins
BEFORE INSERT ON purchase_payments
FOR EACH ROW
BEGIN
  /* BANK TRANSFER (direct deposit) */
  SELECT CASE
    WHEN NEW.method = 'Bank Transfer' AND (
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'online') OR
         (CAST(NEW.amount AS REAL) > 0 AND NEW.vendor_bank_account_id IS NULL)
    )
    THEN RAISE(ABORT, 'Bank Transfer requires company account, transaction #, instrument_type=online; vendor account required for outgoing')
    ELSE 1 END;

  /* CHEQUE (regular incoming) - no vendor bank required */
  SELECT CASE
    WHEN NEW.method = 'Cheque' AND (
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cheque')
    )
    THEN RAISE(ABORT, 'Cheque requires company account, cheque #, instrument_type=cheque; vendor account not required')
    ELSE 1 END;

  /* CROSS CHEQUE (outgoing to vendor) - vendor bank required */
  SELECT CASE
    WHEN NEW.method = 'Cross Cheque' AND (
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cross_cheque') OR
         (CAST(NEW.amount AS REAL) > 0 AND NEW.vendor_bank_account_id IS NULL)
    )
    THEN RAISE(ABORT, 'Cross Cheque requires company account, cheque #, instrument_type=cross_cheque; vendor account required for outgoing')
    ELSE 1 END;

  /* CASH DEPOSIT to vendor’s bank */
  SELECT CASE
    WHEN NEW.method = 'Cash Deposit' AND (
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cash_deposit') OR
         (CAST(NEW.amount AS REAL) > 0 AND NEW.vendor_bank_account_id IS NULL)
    )
    THEN RAISE(ABORT, 'Cash Deposit requires deposit slip #, instrument_type=cash_deposit; vendor account required for outgoing')
    ELSE 1 END;

  /* CASH (hand cash; not a bank movement) */
  SELECT CASE
    WHEN NEW.method = 'Cash' AND (
         NEW.bank_account_id IS NOT NULL OR                              -- no company bank for cash
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type NOT IN ('other')) OR
         NEW.vendor_bank_account_id IS NOT NULL                          -- not a bank transfer to vendor
         /* instrument_no optional for cash */
    )
    THEN RAISE(ABORT, 'Cash should not reference a bank; set bank_account_id NULL, vendor_bank_account_id NULL, instrument_type NULL/other')
    ELSE 1 END;
END;

DROP TRIGGER IF EXISTS trg_pp_method_checks_upd;
CREATE TRIGGER trg_pp_method_checks_upd
BEFORE UPDATE ON purchase_payments
FOR EACH ROW
BEGIN
  /* Apply same rules on UPDATE */
  SELECT CASE
    WHEN NEW.method = 'Bank Transfer' AND (
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'online') OR
         (CAST(NEW.amount AS REAL) > 0 AND NEW.vendor_bank_account_id IS NULL)
    )
    THEN RAISE(ABORT, 'Bank Transfer requires company account, transaction #, instrument_type=online; vendor account required for outgoing')
    ELSE 1 END;

  SELECT CASE
    WHEN NEW.method = 'Cheque' AND (
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cheque')
    )
    THEN RAISE(ABORT, 'Cheque requires company account, cheque #, instrument_type=cheque; vendor account not required')
    ELSE 1 END;

  SELECT CASE
    WHEN NEW.method = 'Cross Cheque' AND (
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cross_cheque') OR
         (CAST(NEW.amount AS REAL) > 0 AND NEW.vendor_bank_account_id IS NULL)
    )
    THEN RAISE(ABORT, 'Cross Cheque requires company account, cheque #, instrument_type=cross_cheque; vendor account required for outgoing')
    ELSE 1 END;

  SELECT CASE
    WHEN NEW.method = 'Cash Deposit' AND (
         NEW.instrument_no IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cash_deposit') OR
         (CAST(NEW.amount AS REAL) > 0 AND NEW.vendor_bank_account_id IS NULL)
    )
    THEN RAISE(ABORT, 'Cash Deposit requires deposit slip #, instrument_type=cash_deposit; vendor account required for outgoing')
    ELSE 1 END;

  /* CASH (hand cash; not a bank movement) */
  SELECT CASE
    WHEN NEW.method = 'Cash' AND (
         NEW.bank_account_id IS NOT NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type NOT IN ('other')) OR
         NEW.vendor_bank_account_id IS NOT NULL
    )
    THEN RAISE(ABORT, 'Cash should not reference a bank; set bank_account_id NULL, vendor_bank_account_id NULL, instrument_type NULL/other')
    ELSE 1 END;
END;


/* Guard: don’t allow applying more credit than available */
DROP TRIGGER IF EXISTS trg_vendor_advances_no_overdraw;
CREATE TRIGGER trg_vendor_advances_no_overdraw
BEFORE INSERT ON vendor_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_purchase'
BEGIN
  SELECT CASE
    WHEN (
      COALESCE((SELECT SUM(CAST(amount AS REAL))
                FROM vendor_advances
                WHERE vendor_id = NEW.vendor_id), 0.0)
      + CAST(NEW.amount AS REAL)  -- NEW.amount negative when applying
    ) < -1e-9
    THEN RAISE(ABORT, 'Insufficient vendor credit')
    ELSE 1
  END;
END;

/* New guard: do not allow applying credit beyond a purchase's remaining due (INSERT) */
DROP TRIGGER IF EXISTS trg_vendor_advances_not_exceed_remaining_due;
CREATE TRIGGER trg_vendor_advances_not_exceed_remaining_due
BEFORE INSERT ON vendor_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_purchase' AND NEW.source_id IS NOT NULL
BEGIN
  /* Ensure referenced purchase exists */
  SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM purchases p WHERE p.purchase_id = NEW.source_id)
      THEN RAISE(ABORT, 'Invalid purchase reference for vendor credit application')
    ELSE 1
  END;

  /* remaining_due = total_amount - cleared paid_amount - advance_payment_applied */
  SELECT CASE
    WHEN (
      COALESCE((SELECT CAST(total_amount AS REAL)            FROM purchases WHERE purchase_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(paid_amount AS REAL)             FROM purchases WHERE purchase_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(advance_payment_applied AS REAL) FROM purchases WHERE purchase_id = NEW.source_id), 0.0)
      + CAST(NEW.amount AS REAL)  /* NEW.amount negative when applying */
    ) < -1e-9
    THEN RAISE(ABORT, 'Cannot apply credit beyond remaining due')
    ELSE 1
  END;
END;

/* New guard: do not allow applying credit beyond a purchase's remaining due (UPDATE) */
DROP TRIGGER IF EXISTS trg_vendor_advances_not_exceed_remaining_due_upd;
CREATE TRIGGER trg_vendor_advances_not_exceed_remaining_due_upd
BEFORE UPDATE ON vendor_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_purchase' AND NEW.source_id IS NOT NULL
BEGIN
  /* Ensure referenced purchase exists */
  SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM purchases p WHERE p.purchase_id = NEW.source_id)
      THEN RAISE(ABORT, 'Invalid purchase reference for vendor credit application')
    ELSE 1
  END;

  /* remaining_due = total - cleared paid - advance_applied
     On UPDATE, advance_applied already includes OLD.amount; check DELTA (NEW.amount - OLD.amount). */
  SELECT CASE
    WHEN (
      COALESCE((SELECT CAST(total_amount AS REAL)            FROM purchases WHERE purchase_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(paid_amount AS REAL)             FROM purchases WHERE purchase_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(advance_payment_applied AS REAL) FROM purchases WHERE purchase_id = NEW.source_id), 0.0)
      + (CAST(NEW.amount AS REAL) - CAST(OLD.amount AS REAL))  /* apply only the change */
    ) < -1e-9
    THEN RAISE(ABORT, 'Cannot apply credit beyond remaining due')
    ELSE 1
  END;
END;

/* Roll up purchase.advance_payment_applied from vendor credit applications */
DROP TRIGGER IF EXISTS trg_adv_applied_from_vendor_ai;
DROP TRIGGER IF EXISTS trg_adv_applied_from_vendor_au;
DROP TRIGGER IF EXISTS trg_adv_applied_from_vendor_ad;

CREATE TRIGGER trg_adv_applied_from_vendor_ai
AFTER INSERT ON vendor_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_purchase' AND NEW.source_id IS NOT NULL
BEGIN
  UPDATE purchases
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM vendor_advances va
           WHERE va.source_type = 'applied_to_purchase'
             AND va.source_id   = NEW.source_id
         ), 0.0))
   WHERE purchase_id = NEW.source_id;
END;

CREATE TRIGGER trg_adv_applied_from_vendor_au
AFTER UPDATE ON vendor_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_purchase' AND NEW.source_id IS NOT NULL
BEGIN
  UPDATE purchases
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM vendor_advances va
           WHERE va.source_type = 'applied_to_purchase'
             AND va.source_id   = NEW.source_id
         ), 0.0))
   WHERE purchase_id = NEW.source_id;
END;

CREATE TRIGGER trg_adv_applied_from_vendor_ad
AFTER DELETE ON vendor_advances
FOR EACH ROW
WHEN OLD.source_type = 'applied_to_purchase' AND OLD.source_id IS NOT NULL
BEGIN
  UPDATE purchases
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM vendor_advances va
           WHERE va.source_type = 'applied_to_purchase'
             AND va.source_id   = OLD.source_id
         ), 0.0))
   WHERE purchase_id = OLD.source_id;
END;

/* Quick balance view */
DROP VIEW IF EXISTS v_vendor_advance_balance;
CREATE VIEW v_vendor_advance_balance AS
SELECT vendor_id,
       COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS balance
FROM vendor_advances
GROUP BY vendor_id;


/* ======================== VIEWS ======================== */

/* Sales totals (per-unit discount) — works for both doc types */
DROP VIEW IF EXISTS sale_detailed_totals;
CREATE VIEW sale_detailed_totals AS
SELECT s.sale_id,
       CAST(s.order_discount AS REAL) AS order_discount,
       COALESCE((
         SELECT SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
         FROM sale_items si WHERE si.sale_id = s.sale_id
       ),0.0) AS subtotal_before_order_discount,
       COALESCE((
         SELECT SUM(CAST(si.quantity AS REAL) * (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
         FROM sale_items si WHERE si.sale_id = s.sale_id
       ),0.0) - CAST(s.order_discount AS REAL) AS calculated_total_amount
FROM sales s;

/* Purchase totals (per-unit discount) */
DROP VIEW IF EXISTS purchase_detailed_totals;
CREATE VIEW purchase_detailed_totals AS
SELECT p.purchase_id,
       CAST(p.order_discount AS REAL) AS order_discount,
       COALESCE((
         SELECT SUM(CAST(pi.quantity AS REAL) * (CAST(pi.purchase_price AS REAL) - CAST(pi.item_discount AS REAL)))
         FROM purchase_items pi WHERE pi.purchase_id = p.purchase_id
       ), 0.0) AS subtotal_before_order_discount,
       COALESCE((
         SELECT SUM(CAST(pi.quantity AS REAL) * (CAST(pi.purchase_price AS REAL) - CAST(pi.item_discount AS REAL)))
         FROM purchase_items pi WHERE pi.purchase_id = p.purchase_id
       ), 0.0) - CAST(p.order_discount AS REAL) AS calculated_total_amount
FROM purchases p;

/* On-hand stock (from latest valuation snapshot per product) */
DROP VIEW IF EXISTS v_stock_on_hand;
CREATE VIEW v_stock_on_hand AS
WITH latest AS (
  SELECT svh.product_id,
         MAX(svh.valuation_id) AS last_vid
  FROM stock_valuation_history svh
  GROUP BY svh.product_id
)
SELECT l.product_id, svh.quantity AS qty_in_base, svh.unit_value, svh.total_value, svh.valuation_date
FROM latest l
JOIN stock_valuation_history svh ON svh.valuation_id = l.last_vid;

/* COGS per sale item using running average at sale date (only for real sales) */
DROP VIEW IF EXISTS sale_item_cogs;
CREATE VIEW sale_item_cogs AS
SELECT
  si.item_id,
  si.sale_id,
  si.product_id,
  -- convert sold quantity to base
  (CAST(si.quantity AS REAL) * COALESCE((
      SELECT CAST(pu.factor_to_base AS REAL)
      FROM product_uoms pu
      WHERE pu.product_id = si.product_id
        AND pu.uom_id     = si.uom_id
      LIMIT 1
  ), 1.0)) AS qty_base,
  -- unit cost at or before sale date
  COALESCE((
    SELECT svh.unit_value
    FROM sales s2
    JOIN stock_valuation_history svh
      ON svh.product_id = si.product_id
     AND DATE(svh.valuation_date) <= DATE(s2.date)
    WHERE s2.sale_id = si.sale_id AND s2.doc_type = 'sale'
    ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
    LIMIT 1
  ), 0.0) AS unit_cost_base,
  -- extended COGS
  ((CAST(si.quantity AS REAL) * COALESCE((
      SELECT CAST(pu.factor_to_base AS REAL)
      FROM product_uoms pu
      WHERE pu.product_id = si.product_id
        AND pu.uom_id     = si.uom_id
      LIMIT 1
  ), 1.0)) *
   COALESCE((
    SELECT svh.unit_value
    FROM sales s2
    JOIN stock_valuation_history svh
      ON svh.product_id = si.product_id
     AND DATE(svh.valuation_date) <= DATE(s2.date)
    WHERE s2.sale_id = si.sale_id AND s2.doc_type = 'sale'
    ORDER BY DATE(svh.valuation_date) DESC, svh.valuation_id DESC
    LIMIT 1
  ), 0.0)
  ) AS cogs_value
FROM sale_items si
JOIN sales s ON s.sale_id = si.sale_id AND s.doc_type = 'sale';

/* Monthly Profit & Loss — exclude quotations */
DROP VIEW IF EXISTS profit_loss_view;
CREATE VIEW profit_loss_view AS
WITH periods AS (
    SELECT DISTINCT strftime('%Y-%m', date) AS period
    FROM (
        SELECT date FROM sales WHERE doc_type = 'sale'
        UNION SELECT date FROM expenses
        UNION SELECT date FROM purchases
    )
),
revenue AS (
    SELECT strftime('%Y-%m', s.date) AS period,
           SUM(CAST(s.total_amount AS REAL)) AS total_revenue
    FROM sales s
    WHERE s.doc_type = 'sale'
    GROUP BY period
),
cogs AS (
    SELECT strftime('%Y-%m', s.date) AS period,
           SUM(c.cogs_value) AS total_cogs
    FROM sales s
    JOIN sale_item_cogs c ON c.sale_id = s.sale_id
    WHERE s.doc_type = 'sale'
    GROUP BY period
),
operating AS (
    SELECT strftime('%Y-%m', date) AS period,
           SUM(CAST(amount AS REAL)) AS total_expenses
    FROM expenses
    GROUP BY period
)
SELECT p.period,
       COALESCE(r.total_revenue, 0.0)  AS revenue,
       COALESCE(c.total_cogs,    0.0)  AS cost_of_goods_sold,
       COALESCE(r.total_revenue, 0.0) - COALESCE(c.total_cogs, 0.0) AS gross_profit,
       COALESCE(o.total_expenses, 0.0) AS operating_expenses,
       COALESCE(r.total_revenue, 0.0) - COALESCE(c.total_cogs, 0.0) - COALESCE(o.total_expenses, 0.0) AS net_profit
FROM periods p
LEFT JOIN revenue  r ON p.period = r.period
LEFT JOIN cogs     c ON p.period = c.period
LEFT JOIN operating o ON p.period = o.period;

/* Running balance per customer */
DROP VIEW IF EXISTS v_customer_advance_balance;
CREATE VIEW v_customer_advance_balance AS
SELECT customer_id,
       COALESCE(SUM(CAST(amount AS REAL)), 0.0) AS balance
FROM customer_advances
GROUP BY customer_id;

/* === Unified bank ledger: per company account, incoming vs outgoing === */
DROP VIEW IF EXISTS v_bank_ledger;
CREATE VIEW v_bank_ledger AS
SELECT
  'sale'  AS src,
  sp.payment_id,
  sp.date,
  CASE WHEN sp.amount > 0 THEN sp.amount ELSE 0.0 END AS amount_in,
  CASE WHEN sp.amount < 0 THEN -sp.amount ELSE 0.0 END AS amount_out,
  sp.method,
  sp.instrument_type,
  sp.instrument_no,
  sp.bank_account_id,
  sp.sale_id            AS doc_id
FROM sale_payments sp
UNION ALL
SELECT
  'purchase' AS src,
  pp.payment_id,
  pp.date,
  CASE WHEN pp.amount < 0 THEN -pp.amount ELSE 0.0 END AS amount_in,  -- vendor refund
  CASE WHEN pp.amount > 0 THEN  pp.amount ELSE 0.0 END AS amount_out,
  pp.method,
  pp.instrument_type,
  pp.instrument_no,
  pp.bank_account_id,
  pp.purchase_id        AS doc_id
FROM purchase_payments pp;

/* Value of purchase returns based on original purchase item pricing */
DROP VIEW IF EXISTS purchase_return_valuations;
CREATE VIEW purchase_return_valuations AS
SELECT
  it.transaction_id,
  it.reference_id      AS purchase_id,
  it.reference_item_id AS item_id,
  it.product_id,
  CAST(it.quantity AS REAL)                        AS qty_returned,     -- purchase_items are base UoM by design
  CAST(pi.purchase_price AS REAL)                  AS unit_buy_price,
  CAST(pi.item_discount  AS REAL)                  AS unit_discount,
  (CAST(it.quantity AS REAL) *
   (CAST(pi.purchase_price AS REAL) - CAST(pi.item_discount AS REAL))
  )                                                AS return_value
FROM inventory_transactions it
JOIN purchase_items pi ON pi.item_id = it.reference_item_id
WHERE it.transaction_type = 'purchase_return';


/* Extended bank ledger with vendor destination account (keeps old view intact) */
DROP VIEW IF EXISTS v_bank_ledger_ext;
CREATE VIEW v_bank_ledger_ext AS
SELECT
  'sale'  AS src,
  sp.payment_id,
  sp.date,
  CASE WHEN sp.amount > 0 THEN sp.amount ELSE 0.0 END AS amount_in,
  CASE WHEN sp.amount < 0 THEN -sp.amount ELSE 0.0 END AS amount_out,
  sp.method,
  sp.instrument_type,
  sp.instrument_no,
  sp.bank_account_id,
  NULL AS vendor_bank_account_id,    -- N/A for sales
  sp.sale_id            AS doc_id
FROM sale_payments sp
UNION ALL
SELECT
  'purchase' AS src,
  pp.payment_id,
  pp.date,
  CASE WHEN pp.amount < 0 THEN -pp.amount ELSE 0.0 END AS amount_in,
  CASE WHEN pp.amount > 0 THEN  pp.amount ELSE 0.0 END AS amount_out,
  pp.method,
  pp.instrument_type,
  pp.instrument_no,
  pp.bank_account_id,
  pp.vendor_bank_account_id,
  pp.purchase_id        AS doc_id
FROM purchase_payments pp;


DROP VIEW IF EXISTS v_purchase_total_mismatch;
CREATE VIEW v_purchase_total_mismatch AS
SELECT p.purchase_id,
       p.total_amount         AS header_total,
       d.calculated_total_amount AS calc_total
FROM purchases p
JOIN purchase_detailed_totals d ON d.purchase_id = p.purchase_id
WHERE ABS(CAST(p.total_amount AS REAL) - CAST(d.calculated_total_amount AS REAL)) > 0.0001;


/* ======================== CUSTOMER-SIDE: BANK FLOW IS INCOMING ONLY ======================== */
/* Per-method requirements for sale_payments (incoming-only via bank); Card/Other left unconstrained */
DROP TRIGGER IF EXISTS trg_sp_method_checks_ins;
DROP TRIGGER IF EXISTS trg_sp_method_checks_upd;

CREATE TRIGGER trg_sp_method_checks_ins
BEFORE INSERT ON sale_payments
FOR EACH ROW
BEGIN
  /* BANK TRANSFER (incoming only) */
  SELECT CASE
    WHEN NEW.method = 'Bank Transfer' AND (
         CAST(NEW.amount AS REAL) <= 0 OR
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no   IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'online')
    )
    THEN RAISE(ABORT, 'Bank Transfer must be incoming (amount>0) and requires company bank, txn #, instrument_type=online')
    ELSE 1 END;

  /* CHEQUE (incoming only) */
  SELECT CASE
    WHEN NEW.method = 'Cheque' AND (
         CAST(NEW.amount AS REAL) <= 0 OR
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no   IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cross_cheque')
    )
    THEN RAISE(ABORT, 'Cheque must be incoming (amount>0) and requires company bank, cheque #, instrument_type=cross_cheque')
    ELSE 1 END;

  /* CASH DEPOSIT (incoming only) */
  SELECT CASE
    WHEN NEW.method = 'Cash Deposit' AND (
         CAST(NEW.amount AS REAL) <= 0 OR
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no   IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cash_deposit')
    )
    THEN RAISE(ABORT, 'Cash Deposit must be incoming (amount>0) and requires company bank + deposit slip #, instrument_type=cash_deposit')
    ELSE 1 END;

  /* CASH (no bank refs; can be + or -) */
  SELECT CASE
    WHEN NEW.method = 'Cash' AND (
         NEW.bank_account_id IS NOT NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type NOT IN ('other'))
         /* instrument_no optional */
    )
    THEN RAISE(ABORT, 'Cash must not reference a bank; set bank_account_id NULL and instrument_type NULL/other')
    ELSE 1 END;
END;

CREATE TRIGGER trg_sp_method_checks_upd
BEFORE UPDATE ON sale_payments
FOR EACH ROW
BEGIN
  /* Mirror rules on UPDATE */
  SELECT CASE
    WHEN NEW.method = 'Bank Transfer' AND (
         CAST(NEW.amount AS REAL) <= 0 OR
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no   IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'online')
    )
    THEN RAISE(ABORT, 'Bank Transfer must be incoming (amount>0) and requires company bank, txn #, instrument_type=online')
    ELSE 1 END;

  SELECT CASE
    WHEN NEW.method = 'Cheque' AND (
         CAST(NEW.amount AS REAL) <= 0 OR
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no   IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cross_cheque')
    )
    THEN RAISE(ABORT, 'Cheque must be incoming (amount>0) and requires company bank, cheque #, instrument_type=cross_cheque')
    ELSE 1 END;

  SELECT CASE
    WHEN NEW.method = 'Cash Deposit' AND (
         CAST(NEW.amount AS REAL) <= 0 OR
         NEW.bank_account_id IS NULL OR
         NEW.instrument_no   IS NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type <> 'cash_deposit')
    )
    THEN RAISE(ABORT, 'Cash Deposit must be incoming (amount>0) and requires company bank + deposit slip #, instrument_type=cash_deposit')
    ELSE 1 END;

  SELECT CASE
    WHEN NEW.method = 'Cash' AND (
         NEW.bank_account_id IS NOT NULL OR
         (NEW.instrument_type IS NOT NULL AND NEW.instrument_type NOT IN ('other'))
    )
    THEN RAISE(ABORT, 'Cash must not reference a bank; set bank_account_id NULL and instrument_type NULL/other')
    ELSE 1 END;
END;

/* ======================== CUSTOMER CREDIT ↔ SALE ROLLOUPS ======================== */
/* Keep sales.advance_payment_applied in sync with customer_advances applications */

DROP TRIGGER IF EXISTS trg_adv_applied_from_customer_ai;
CREATE TRIGGER trg_adv_applied_from_customer_ai
AFTER INSERT ON customer_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_sale' AND NEW.source_id IS NOT NULL
BEGIN
  UPDATE sales
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM customer_advances ca
           WHERE ca.source_type = 'applied_to_sale'
             AND ca.source_id   = NEW.source_id
         ), 0.0))
   WHERE sale_id = NEW.source_id;
END;

-- Handle UPDATEs where the NEW row is an application to a sale
DROP TRIGGER IF EXISTS trg_adv_applied_from_customer_au_new;
CREATE TRIGGER trg_adv_applied_from_customer_au_new
AFTER UPDATE ON customer_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_sale' AND NEW.source_id IS NOT NULL
BEGIN
  UPDATE sales
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM customer_advances ca
           WHERE ca.source_type = 'applied_to_sale'
             AND ca.source_id   = NEW.source_id
         ), 0.0))
   WHERE sale_id = NEW.source_id;
END;

-- Handle UPDATEs where the OLD row used to affect another sale (source_id changed or type changed)
DROP TRIGGER IF EXISTS trg_adv_applied_from_customer_au_old;
CREATE TRIGGER trg_adv_applied_from_customer_au_old
AFTER UPDATE ON customer_advances
FOR EACH ROW
WHEN OLD.source_type = 'applied_to_sale' AND OLD.source_id IS NOT NULL
BEGIN
  UPDATE sales
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM customer_advances ca
           WHERE ca.source_type = 'applied_to_sale'
             AND ca.source_id   = OLD.source_id
         ), 0.0))
   WHERE sale_id = OLD.source_id;
END;

DROP TRIGGER IF EXISTS trg_adv_applied_from_customer_ad;
CREATE TRIGGER trg_adv_applied_from_customer_ad
AFTER DELETE ON customer_advances
FOR EACH ROW
WHEN OLD.source_type = 'applied_to_sale' AND OLD.source_id IS NOT NULL
BEGIN
  UPDATE sales
     SET advance_payment_applied =
         MAX(0.0, COALESCE((
           SELECT SUM(-CAST(amount AS REAL))
           FROM customer_advances ca
           WHERE ca.source_type = 'applied_to_sale'
             AND ca.source_id   = OLD.source_id
         ), 0.0))
   WHERE sale_id = OLD.source_id;
END;


/* ======================== CUSTOMER CREDIT GUARD (NO OVER-APPLICATION) ======================== */
/* Prevent applying more credit to a sale than its remaining due (header total - cash/bank paid - credit already applied). */

DROP TRIGGER IF EXISTS trg_customer_advances_not_exceed_remaining_due;
CREATE TRIGGER trg_customer_advances_not_exceed_remaining_due
BEFORE INSERT ON customer_advances
FOR EACH ROW
WHEN NEW.source_type = 'applied_to_sale' AND NEW.source_id IS NOT NULL
BEGIN
  /* Ensure referenced sale exists */
  SELECT CASE
    WHEN NOT EXISTS (SELECT 1 FROM sales s WHERE s.sale_id = NEW.source_id)
      THEN RAISE(ABORT, 'Invalid sale reference for customer credit application')
    ELSE 1
  END;

  /* remaining_due = total_amount - paid_amount - advance_payment_applied */
  SELECT CASE
    WHEN (
      COALESCE((SELECT CAST(total_amount AS REAL)            FROM sales WHERE sale_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(paid_amount AS REAL)             FROM sales WHERE sale_id = NEW.source_id), 0.0)
      -
      COALESCE((SELECT CAST(advance_payment_applied AS REAL) FROM sales WHERE sale_id = NEW.source_id), 0.0)
      + CAST(NEW.amount AS REAL)  /* NEW.amount is negative when applying credit */
    ) < -1e-9
    THEN RAISE(ABORT, 'Cannot apply credit beyond remaining due')
    ELSE 1
  END;
END;

"""

def _ensure_customer_is_active(conn: sqlite3.Connection) -> None:
    """
    Safe migration for older DBs that created `customers` before `is_active` existed.
    Adds the column if missing. No-op if already present.
    """
    cur = conn.execute("PRAGMA table_info(customers);")
    cols = {row[1] for row in cur.fetchall()}  # row[1] = name
    if "is_active" not in cols:
        conn.execute(
            "ALTER TABLE customers "
            "ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1));"
        )

def init_schema(db_path: Path | str = "myshop.db") -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        # Apply (idempotent) schema
        conn.executescript(SQL)
        # Backfill migration for existing DBs missing customers.is_active
        _ensure_customer_is_active(conn)
        conn.commit()
    print(f"✓ DB applied to {db_path}")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "data" / "myshop.db"
    init_schema(target)
