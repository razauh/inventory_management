-- tests/seed_common.sql  (idempotent)
PRAGMA foreign_keys = ON;
BEGIN;

-- ---------- Company (fixed PK=1) ----------
INSERT INTO company_info(company_id, company_name, address)
VALUES (1, 'Test Co', 'N/A')
ON CONFLICT(company_id) DO UPDATE SET
  company_name = excluded.company_name,
  address      = excluded.address;

-- ---------- Users (username is UNIQUE) ----------
INSERT INTO users(username, password_hash, full_name, role, is_active)
VALUES ('ops', 'x', 'Op User', 'admin', 1)
ON CONFLICT(username) DO UPDATE SET
  password_hash = excluded.password_hash,
  full_name     = excluded.full_name,
  role          = excluded.role,
  is_active     = excluded.is_active;

-- ---------- Company bank accounts (UNIQUE: company_id, label) ----------
INSERT INTO company_bank_accounts(company_id, label, bank_name, account_no, is_active)
VALUES
  (1, 'Meezan — Current', 'Meezan', '001-123456', 1),
  (1, 'HBL — Current',    'HBL',    '002-987654', 1)
ON CONFLICT(company_id, label) DO UPDATE SET
  bank_name = excluded.bank_name,
  account_no = excluded.account_no,
  is_active  = excluded.is_active;

-- ---------- UoMs (unit_name is UNIQUE) ----------
INSERT INTO uoms(unit_name) VALUES ('Piece')
ON CONFLICT(unit_name) DO NOTHING;

INSERT INTO uoms(unit_name) VALUES ('Box')
ON CONFLICT(unit_name) DO NOTHING;

-- ---------- Products (no UNIQUE on name → guard with WHERE NOT EXISTS) ----------
INSERT INTO products(name, description, min_stock_level)
SELECT 'Widget A', 'A', 0
WHERE NOT EXISTS (SELECT 1 FROM products WHERE name='Widget A');

INSERT INTO products(name, description, min_stock_level)
SELECT 'Widget B', 'B', 0
WHERE NOT EXISTS (SELECT 1 FROM products WHERE name='Widget B');

-- ---------- Product UoMs (UNIQUE: product_id, uom_id) ----------
-- Base UoM for Widget A: Piece
INSERT INTO product_uoms(product_id, uom_id, is_base, factor_to_base)
SELECT p.product_id, u.uom_id, 1, 1.0
FROM products p, uoms u
WHERE p.name='Widget A' AND u.unit_name='Piece'
ON CONFLICT(product_id, uom_id) DO UPDATE SET
  is_base        = excluded.is_base,
  factor_to_base = excluded.factor_to_base;

-- Secondary UoM for Widget A: Box (factor 10)
INSERT INTO product_uoms(product_id, uom_id, is_base, factor_to_base)
SELECT p.product_id, u.uom_id, 0, 10.0
FROM products p, uoms u
WHERE p.name='Widget A' AND u.unit_name='Box'
ON CONFLICT(product_id, uom_id) DO UPDATE SET
  is_base        = excluded.is_base,
  factor_to_base = excluded.factor_to_base;

-- Base UoM for Widget B: Piece
INSERT INTO product_uoms(product_id, uom_id, is_base, factor_to_base)
SELECT p.product_id, u.uom_id, 1, 1.0
FROM products p, uoms u
WHERE p.name='Widget B' AND u.unit_name='Piece'
ON CONFLICT(product_id, uom_id) DO UPDATE SET
  is_base        = excluded.is_base,
  factor_to_base = excluded.factor_to_base;

-- ---------- Vendor (no UNIQUE on name → guard with WHERE NOT EXISTS) ----------
INSERT INTO vendors(name, contact_info, address)
SELECT 'Vendor X', 'x@vendor.test', 'Karachi'
WHERE NOT EXISTS (SELECT 1 FROM vendors WHERE name='Vendor X');

-- ---------- Vendor bank account (UNIQUE: vendor_id, label) ----------
INSERT INTO vendor_bank_accounts(
  vendor_id, label, bank_name, account_no, iban, routing_no, is_primary, is_active
)
SELECT v.vendor_id, 'VendorX — HBL', 'HBL', 'V-111', 'PK00HBLVENDORX', NULL, 1, 1
FROM vendors v
WHERE v.name='Vendor X'
ON CONFLICT(vendor_id, label) DO UPDATE SET
  bank_name = excluded.bank_name,
  account_no = excluded.account_no,
  iban = excluded.iban,
  routing_no = excluded.routing_no,
  is_primary = excluded.is_primary,
  is_active  = excluded.is_active;

COMMIT;
