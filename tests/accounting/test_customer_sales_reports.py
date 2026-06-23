"""Characterization tests for report/ dashboard financial reads."""

from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService, SalesDashboardMetrics


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sales (
            sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, order_discount REAL DEFAULT 0,
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount REAL DEFAULT 0, advance_payment_applied REAL DEFAULT 0,
            notes TEXT, created_by INTEGER, doc_type TEXT DEFAULT 'sale',
            source_type TEXT DEFAULT 'direct', source_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS sale_items (
            item_id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id TEXT,
            product_id INTEGER, quantity REAL, uom_id INTEGER,
            unit_price REAL, item_discount REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS products (product_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE IF NOT EXISTS uoms (uom_id INTEGER PRIMARY KEY, unit_name TEXT);
        CREATE TABLE IF NOT EXISTS expenses (
            expense_id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, amount REAL,
            category TEXT, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS purchases (
            purchase_id TEXT PRIMARY KEY, date TEXT, total_amount REAL,
            paid_amount REAL DEFAULT 0, advance_payment_applied REAL DEFAULT 0,
            doc_type TEXT DEFAULT 'purchase'
        );
        CREATE TABLE IF NOT EXISTS purchase_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id TEXT,
            date TEXT, amount REAL, clearing_state TEXT, cleared_date TEXT
        );
        CREATE TABLE IF NOT EXISTS purchase_refunds (
            refund_id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id TEXT,
            date TEXT, amount REAL, clearing_state TEXT, cleared_date TEXT
        );
        CREATE TABLE IF NOT EXISTS sale_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT, date TEXT, amount REAL, method TEXT,
            clearing_state TEXT, cleared_date TEXT
        );
        CREATE TABLE IF NOT EXISTS sale_financial_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT, event_date TEXT, revenue REAL, cogs REAL
        );
        CREATE VIEW IF NOT EXISTS sale_receivable_totals AS
        SELECT s.sale_id,
               MAX(0.0, CAST(s.total_amount AS REAL) - COALESCE(CAST(s.order_discount AS REAL), 0.0))
                 AS canonical_total_amount,
               MAX(0.0, COALESCE(CAST(s.paid_amount AS REAL), 0.0)) AS paid_amount,
               0.0 AS advance_payment_applied,
               MAX(0.0, MAX(0.0, CAST(s.total_amount AS REAL)
                 - COALESCE(CAST(s.order_discount AS REAL), 0.0))
                 - MAX(0.0, COALESCE(CAST(s.paid_amount AS REAL), 0.0))
               ) AS remaining_due
        FROM sales s;
        CREATE VIEW IF NOT EXISTS sale_detailed_totals AS
        SELECT s.sale_id, CAST(s.order_discount AS REAL) AS order_discount,
               CAST(s.total_amount AS REAL) AS subtotal_before_order_discount,
               CAST(s.total_amount AS REAL) - CAST(s.order_discount AS REAL) AS calculated_total_amount,
               0.0 AS returned_value,
               MAX(0.0, CAST(s.total_amount AS REAL)) AS net_total_amount
        FROM sales s;
        """
    )


def test_dashboard_sales_metrics_match_current_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute(
        "INSERT INTO sale_financial_events (sale_id, event_date, revenue, cogs) "
        "VALUES ('S1', '2026-06-21', 100, 60)"
    )
    conn.execute(
        "INSERT INTO expenses (date, amount) VALUES ('2026-06-21', 20)"
    )
    conn.execute(
        "INSERT INTO sales (sale_id, customer_id, date, total_amount, "
        "paid_amount, doc_type) VALUES ('S1', 1, '2026-06-21', 100, 40, 'sale')"
    )
    conn.execute(
        "INSERT INTO sale_payments (sale_id, date, amount, clearing_state, cleared_date) "
        "VALUES ('S1', '2026-06-22', 40, 'cleared', '2026-06-22')"
    )

    svc = AccountingService(conn)
    metrics = svc.get_sales_dashboard_metrics('2026-06-01', '2026-06-30')

    assert float(metrics.total_sales) == 100.0
    assert float(metrics.total_cogs) == 60.0
    assert float(metrics.total_expenses) == 20.0
    assert float(metrics.receipts_cleared) == 40.0
    assert metrics.as_of == '2026-06-30'


def test_customer_receivable_summary_ignores_posted_uncleared_payments():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS
        SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance
        FROM customer_advances GROUP BY customer_id;
        """
    )

    # Insert customer and sale
    conn.execute("INSERT INTO sales (sale_id, customer_id, date, total_amount, paid_amount) VALUES ('S1', 1, '2026-06-20', 100.0, 0.0)")

    # Add a posted but uncleared payment
    conn.execute(
        "INSERT INTO sale_payments (sale_id, date, amount, clearing_state) "
        "VALUES ('S1', '2026-06-22', 40.0, 'posted')"
    )

    svc = AccountingService(conn)
    summary = svc.get_customer_receivable_summary(1)

    # Since it is posted but not cleared, paid_amount on sale is 0,
    # so remaining due should still be 100.0, NOT 60.0!
    import pytest
    assert float(summary.open_due_sum) == pytest.approx(100.0)
    conn.close()


def test_customer_receivable_summary_matches_sale_receivable_totals_remaining_due():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT
        );
        """
    )
    conn.execute(
        """
        CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS
        SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance
        FROM customer_advances GROUP BY customer_id;
        """
    )

    conn.execute("INSERT INTO sales (sale_id, customer_id, date, total_amount, paid_amount) VALUES ('S1', 1, '2026-06-20', 100.0, 40.0)")
    conn.execute("INSERT INTO sales (sale_id, customer_id, date, total_amount, paid_amount) VALUES ('S2', 1, '2026-06-21', 50.0, 50.0)")

    svc = AccountingService(conn)
    summary = svc.get_customer_receivable_summary(1)

    import pytest
    # Remaining due should be (100 - 40) + (50 - 50) = 60.0
    assert float(summary.open_due_sum) == pytest.approx(60.0)
    conn.close()

