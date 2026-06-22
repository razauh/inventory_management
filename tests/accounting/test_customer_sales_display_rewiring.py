"""Characterization tests for sales/customer display panel rewiring."""

from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY, name TEXT, contact_info TEXT, address TEXT
        );
        CREATE TABLE IF NOT EXISTS sales (
            sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0,
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount REAL DEFAULT 0,
            advance_payment_applied REAL DEFAULT 0,
            notes TEXT, created_by INTEGER,
            doc_type TEXT DEFAULT 'sale',
            source_type TEXT DEFAULT 'direct', source_id INTEGER
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
            bank_account_id INTEGER, instrument_type TEXT,
            instrument_no TEXT, instrument_date TEXT, deposited_date TEXT,
            cleared_date TEXT, clearing_state TEXT, ref_no TEXT,
            notes TEXT, created_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS customer_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT, method TEXT,
            bank_account_id INTEGER, reference_no TEXT, notes TEXT,
            created_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS inventory_transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER, quantity REAL, uom_id INTEGER,
            transaction_type TEXT, reference_table TEXT,
            reference_id TEXT, reference_item_id INTEGER,
            date TEXT, posted_at TEXT, txn_seq INTEGER, notes TEXT,
            created_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS sale_return_snapshots (
            transaction_id INTEGER PRIMARY KEY,
            sale_id TEXT, item_id INTEGER, product_id INTEGER,
            uom_id INTEGER, returned_quantity REAL,
            return_value REAL, allocated_order_discount REAL,
            cogs_reversal_value REAL, return_date TEXT,
            unit_sale_price REAL, unit_discount REAL, net_unit_price REAL
        );
        CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS
        SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance
        FROM customer_advances GROUP BY customer_id;
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


def test_sales_detail_payload_routes_through_accounting_service():
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

    from database.repositories.sales_repo import SalesRepo
    repo = SalesRepo(conn)
    snapshot = repo.get_sale_detail_snapshot('S1')

    assert snapshot is not None
    assert "summary" in snapshot
    assert "header" in snapshot
    assert "items" in snapshot
    assert snapshot["header"]["sale_id"] == "S1"

    summary = snapshot["summary"]
    assert "total_amount" in summary
    assert "gross_total_amount" in summary
    assert "net_total_amount" in summary
    assert "remaining_due" in summary


def test_customer_detail_financial_payload_routes_through_accounting_service():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute("INSERT INTO customers (customer_id, name) VALUES (1, 'Test')")
    conn.execute("INSERT INTO products (product_id, name) VALUES (1, 'Widget')")
    conn.execute("INSERT INTO uoms (uom_id, unit_name) VALUES (1, 'pcs')")

    conn.execute(
        "INSERT INTO sales (sale_id, customer_id, date, total_amount, "
        "order_discount, doc_type) VALUES ('S1', 1, '2026-06-21', 100, 0, 'sale')"
    )
    conn.execute(
        "INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, "
        "unit_price, item_discount) VALUES ('S1', 1, 1, 1, 100, 0)"
    )
    conn.execute(
        "INSERT INTO sale_payments (sale_id, date, amount, method, clearing_state) "
        "VALUES ('S1', '2026-06-22', 40, 'Cash', 'cleared')"
    )
    conn.execute(
        "UPDATE sales SET paid_amount = 40, payment_status = 'partial' WHERE sale_id = 'S1'"
    )
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-06-23', 20, 'deposit')"
    )

    svc = AccountingService(conn)
    summary = svc.get_customer_receivable_summary(1)

    assert summary.customer_id == 1
    assert summary.sales_count == 1
    assert float(summary.credit_balance) == 20
    assert summary.last_sale_date is not None
    assert summary.last_payment_date is not None
    assert summary.last_advance_date is not None
