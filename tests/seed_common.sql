-- Seed data for tests

-- Company Info
INSERT OR IGNORE INTO company_info (company_id, company_name) VALUES (1, 'Test Company');

-- Users
INSERT OR IGNORE INTO users (username, password_hash, full_name, role) VALUES ('ops', 'hash', 'Ops User', 'admin');

-- Vendors
INSERT OR IGNORE INTO vendors (name, contact_info) VALUES ('Vendor X', 'Contact Info X');

-- Company Bank Accounts
INSERT OR IGNORE INTO company_bank_accounts (company_id, label, bank_name, account_no) VALUES 
(1, 'Meezan — Current', 'Meezan Bank', '1234567890'),
(1, 'HBL — Current', 'HBL', '0987654321');

-- Vendor Bank Accounts
INSERT OR IGNORE INTO vendor_bank_accounts (vendor_id, label, is_primary) 
SELECT vendor_id, 'Vendor X Bank', 1 FROM vendors WHERE name='Vendor X';

-- UOMs
INSERT OR IGNORE INTO uoms (unit_name) VALUES ('Piece'), ('Box');

-- Products
INSERT OR IGNORE INTO products (name, min_stock_level) VALUES ('Widget A', 10), ('Widget B', 20);

-- Product UOMs (Base)
INSERT OR IGNORE INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
SELECT p.product_id, u.uom_id, 1, 1.0
FROM products p, uoms u
WHERE p.name IN ('Widget A', 'Widget B') AND u.unit_name = 'Piece';
