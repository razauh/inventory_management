"""Characterization tests for quotation behavior."""

from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService, QuotationConversionPayload


def test_quotation_financials_match_current_controller_context():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0,
            doc_type TEXT DEFAULT 'sale', quotation_status TEXT);
        CREATE TABLE sale_items (item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT, product_id INTEGER, quantity REAL,
            uom_id INTEGER, unit_price REAL, item_discount REAL DEFAULT 0);
        CREATE TABLE products (product_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE uoms (uom_id INTEGER PRIMARY KEY, unit_name TEXT);
        INSERT INTO sales (sale_id, customer_id, date, total_amount, order_discount, doc_type, quotation_status)
        VALUES ('Q1', 1, '2026-06-21', 100, 10, 'quotation', 'draft');
        INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, unit_price, item_discount)
        VALUES ('Q1', 1, 2, 1, 50, 5);
    """)
    svc = AccountingService(conn)
    result = svc.get_quotation_financials('Q1')
    assert result.quotation_id == 'Q1'
    assert result.context.get("id") == 'Q1'


def test_quotation_conversion_matches_current_sales_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0, paid_amount REAL DEFAULT 0,
            advance_payment_applied REAL DEFAULT 0, payment_status TEXT DEFAULT 'unpaid',
            notes TEXT, created_by INTEGER, doc_type TEXT DEFAULT 'sale',
            source_type TEXT DEFAULT 'direct', source_id INTEGER,
            quotation_status TEXT, expiry_date TEXT);
        CREATE TABLE sale_items (item_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT, product_id INTEGER, quantity REAL, uom_id INTEGER,
            unit_price REAL, item_discount REAL DEFAULT 0);
        CREATE TABLE inventory_transactions (transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER, quantity REAL, uom_id INTEGER, transaction_type TEXT,
            reference_table TEXT, reference_id TEXT, reference_item_id INTEGER,
            date TEXT, txn_seq INTEGER, notes TEXT, created_by INTEGER);
        INSERT INTO sales (sale_id, customer_id, date, total_amount, order_discount,
            doc_type, quotation_status)
        VALUES ('Q1', 1, '2026-06-21', 100, 10, 'quotation', 'draft');
    """)
    svc = AccountingService(conn)

    # Valid conversion
    svc.validate_quotation_conversion('Q1')

    payload = QuotationConversionPayload(quotation_id='Q1', new_sale_id='SO1', date='2026-06-22', created_by=1)
    result = svc.record_quotation_conversion_event(payload)
    assert result.quotation_id == 'Q1'
    assert result.sale_id == 'SO1'

    # Check quotation was marked accepted
    row = conn.execute("SELECT quotation_status FROM sales WHERE sale_id='Q1'").fetchone()
    assert row["quotation_status"] == 'accepted'


def test_quotation_payment_blocking_is_preserved():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, doc_type TEXT DEFAULT 'sale', quotation_status TEXT);
        INSERT INTO sales (sale_id, customer_id, date, total_amount, doc_type, quotation_status)
        VALUES ('Q1', 1, '2026-06-21', 100, 'quotation', 'accepted');
    """)
    svc = AccountingService(conn)
    try:
        svc.validate_quotation_conversion('Q1')
        assert False, "expected ValueError"
    except ValueError as e:
        assert "cannot be converted" in str(e).lower()
