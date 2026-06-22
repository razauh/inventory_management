"""Characterization tests for invoice/ quotation financial sourcing."""

from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY, name TEXT, contact_info TEXT, address TEXT
        );
        CREATE TABLE IF NOT EXISTS company_info (
            company_name TEXT, address TEXT, phone TEXT, email TEXT,
            tax_id TEXT, reg_id TEXT
        );
        CREATE TABLE IF NOT EXISTS sales (
            sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0,
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount REAL DEFAULT 0, advance_payment_applied REAL DEFAULT 0,
            notes TEXT, created_by INTEGER, doc_type TEXT DEFAULT 'sale',
            source_type TEXT DEFAULT 'direct', source_id INTEGER,
            quotation_status TEXT, expiry_date TEXT
        );
        CREATE TABLE IF NOT EXISTS sale_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT,
            product_id INTEGER, quantity REAL, uom_id INTEGER,
            unit_price REAL, item_discount REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS products (
            product_id INTEGER PRIMARY KEY, name TEXT
        );
        CREATE TABLE IF NOT EXISTS uoms (
            uom_id INTEGER PRIMARY KEY, unit_name TEXT
        );
        CREATE TABLE IF NOT EXISTS sale_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT, date TEXT, amount REAL, method TEXT,
            clearing_state TEXT, bank_account_id INTEGER,
            instrument_type TEXT, instrument_no TEXT
        );
        CREATE TABLE IF NOT EXISTS company_bank_accounts (
            account_id INTEGER PRIMARY KEY, label TEXT,
            bank_name TEXT, account_title TEXT, account_no TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS customer_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT
        );
        CREATE TABLE IF NOT EXISTS sale_return_snapshots (
            transaction_id INTEGER PRIMARY KEY,
            sale_id TEXT, item_id INTEGER, product_id INTEGER,
            uom_id INTEGER, returned_quantity REAL,
            return_value REAL, return_date TEXT
        );
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER, quantity REAL, uom_id INTEGER,
            transaction_type TEXT, reference_table TEXT,
            reference_id TEXT, reference_item_id INTEGER,
            date TEXT, notes TEXT, created_by INTEGER
        );
        CREATE VIEW IF NOT EXISTS sale_detailed_totals AS
        SELECT s.sale_id, CAST(s.order_discount AS REAL) AS order_discount,
               COALESCE((SELECT SUM(CAST(si.quantity AS REAL) *
                 (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                 FROM sale_items si WHERE si.sale_id = s.sale_id),0.0)
               AS subtotal_before_order_discount,
               COALESCE((SELECT SUM(CAST(si.quantity AS REAL) *
                 (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                 FROM sale_items si WHERE si.sale_id = s.sale_id),0.0)
               - CAST(s.order_discount AS REAL) AS calculated_total_amount,
               0.0 AS returned_value,
               MAX(0.0, COALESCE((SELECT SUM(CAST(si.quantity AS REAL) *
                 (CAST(si.unit_price AS REAL) - CAST(si.item_discount AS REAL)))
                 FROM sale_items si WHERE si.sale_id = s.sale_id),0.0)
               - CAST(s.order_discount AS REAL)) AS net_total_amount
        FROM sales s;
        CREATE VIEW IF NOT EXISTS sale_receivable_totals AS
        SELECT s.sale_id,
               MAX(0.0, CAST(sdt.net_total_amount AS REAL)) AS canonical_total_amount,
               MAX(0.0, COALESCE(CAST(s.paid_amount AS REAL), 0.0)) AS paid_amount,
               MAX(0.0, COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0)) AS advance_payment_applied,
               MAX(0.0, MAX(0.0, CAST(sdt.net_total_amount AS REAL))
                 - MAX(0.0, COALESCE(CAST(s.paid_amount AS REAL), 0.0))
                 - MAX(0.0, COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0))
               ) AS remaining_due
        FROM sales s JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id;
        """
    )


def test_sale_invoice_financials_match_current_controller_context():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute("INSERT INTO customers (customer_id, name) VALUES (1, 'Test')")
    conn.execute("INSERT INTO products (product_id, name) VALUES (1, 'Widget')")
    conn.execute("INSERT INTO uoms (uom_id, unit_name) VALUES (1, 'pcs')")

    conn.execute(
        "INSERT INTO sales (sale_id, customer_id, date, total_amount, "
        "order_discount, doc_type) VALUES ('S1', 1, '2026-06-21', 100, 10, 'sale')"
    )
    conn.execute(
        "INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, "
        "unit_price, item_discount) VALUES ('S1', 1, 2, 1, 50, 5)"
    )
    conn.execute(
        "INSERT INTO sale_payments (sale_id, date, amount, method, clearing_state) "
        "VALUES ('S1', '2026-06-22', 60, 'Cash', 'cleared')"
    )
    conn.execute(
        "UPDATE sales SET paid_amount = 60, payment_status = 'partial' WHERE sale_id = 'S1'"
    )
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id) "
        "VALUES (1, '2026-06-23', 20, 'return_credit', 'S1')"
    )

    svc = AccountingService(conn)
    result = svc.get_sale_invoice_financials('S1')
    ctx = result.context

    assert 'returns' in ctx
    assert 'return_credit' in ctx
    assert 'applied_credit' in ctx
    assert 'paid_amount' in ctx
    assert ctx['paid_amount'] == 60.0
    assert float(ctx['return_credit']) == 20.0
    assert float(ctx['remaining']) >= 0


def test_quotation_invoice_financials_match_current_controller_context():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute("INSERT INTO customers (customer_id, name) VALUES (1, 'Test')")
    conn.execute("INSERT INTO products (product_id, name) VALUES (1, 'Widget')")
    conn.execute("INSERT INTO uoms (uom_id, unit_name) VALUES (1, 'pcs')")

    conn.execute(
        "INSERT INTO sales (sale_id, customer_id, date, total_amount, "
        "order_discount, doc_type, quotation_status, expiry_date) "
        "VALUES ('Q1', 1, '2026-06-21', 100, 10, 'quotation', 'draft', '2026-07-21')"
    )
    conn.execute(
        "INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, "
        "unit_price, item_discount) VALUES ('Q1', 1, 2, 1, 50, 5)"
    )

    svc = AccountingService(conn)
    result = svc.get_quotation_financials('Q1')
    assert result.quotation_id == 'Q1'
    assert result.context == {"id": "Q1"}
