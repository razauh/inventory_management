"""Characterization tests for customer statement/history."""

from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService
from modules.customer.history import CustomerHistoryService


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, contact_info TEXT, address TEXT
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
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, code TEXT
        );
        CREATE TABLE IF NOT EXISTS uoms (
            uom_id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_name TEXT
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
            unit_sale_price REAL, unit_discount REAL,
            net_unit_price REAL
        );
        CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS
        SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance
        FROM customer_advances GROUP BY customer_id;
        """
    )
    conn.executescript(
        """
        CREATE VIEW IF NOT EXISTS sale_detailed_totals AS
        SELECT s.sale_id,
               CAST(s.order_discount AS REAL) AS order_discount,
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
               MAX(0.0, COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0))
                 AS advance_payment_applied,
               MAX(0.0, MAX(0.0, CAST(sdt.net_total_amount AS REAL))
                 - MAX(0.0, COALESCE(CAST(s.paid_amount AS REAL), 0.0))
                 - MAX(0.0, COALESCE(CAST(s.advance_payment_applied AS REAL), 0.0))
               ) AS remaining_due
        FROM sales s
        JOIN sale_detailed_totals sdt ON sdt.sale_id = s.sale_id;
        """
    )


def test_customer_statement_matches_current_history_service():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute("INSERT INTO customers (customer_id, name) VALUES (1, 'Test')")
    conn.execute(
        "INSERT INTO products (product_id, name) VALUES (1, 'Widget')"
    )
    conn.execute("INSERT INTO uoms (uom_id, unit_name) VALUES (1, 'pcs')")

    # Create a sale
    conn.execute(
        "INSERT INTO sales (sale_id, customer_id, date, total_amount, "
        "order_discount, doc_type) VALUES ('S1', 1, '2026-06-21', 100, 0, 'sale')"
    )
    conn.execute(
        "INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, "
        "unit_price, item_discount) VALUES ('S1', 1, 1, 1, 100, 0)"
    )

    # Add a payment
    conn.execute(
        "INSERT INTO sale_payments (sale_id, date, amount, method, clearing_state) "
        "VALUES ('S1', '2026-06-22', 60, 'Cash', 'cleared')"
    )
    conn.execute(
        "UPDATE sales SET paid_amount = 60, payment_status = 'partial' WHERE sale_id = 'S1'"
    )

    # Add a credit deposit
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-06-23', 30, 'deposit')"
    )

    svc = AccountingService(conn)
    history = svc.get_customer_history(1)

    assert "summary" in history
    assert "sales" in history
    assert "payments" in history
    assert "advances" in history
    assert "timeline" in history

    assert len(history["sales"]) == 1
    assert len(history["payments"]) == 1
    assert len(history["advances"]["entries"]) == 1
    assert float(history["advances"]["balance"]) == 30

    assert history["summary"]["customer_name"] == "Test"
    assert history["summary"]["sales_count"] == 1


def test_customer_statement_preserves_timeline_order_and_event_types():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute("INSERT INTO customers (customer_id, name) VALUES (1, 'Test')")
    conn.execute("INSERT INTO products (product_id, name) VALUES (1, 'Widget')")
    conn.execute("INSERT INTO uoms (uom_id, unit_name) VALUES (1, 'pcs')")

    # Sale
    conn.execute(
        "INSERT INTO sales (sale_id, customer_id, date, total_amount, "
        "order_discount, doc_type) VALUES ('S1', 1, '2026-06-21', 100, 0, 'sale')"
    )
    conn.execute(
        "INSERT INTO sale_items (sale_id, product_id, quantity, uom_id, "
        "unit_price, item_discount) VALUES ('S1', 1, 1, 1, 100, 0)"
    )

    # Payment
    conn.execute(
        "INSERT INTO sale_payments (sale_id, date, amount, method, clearing_state) "
        "VALUES ('S1', '2026-06-22', 100, 'Cash', 'cleared')"
    )
    conn.execute(
        "UPDATE sales SET paid_amount = 100, payment_status = 'paid' WHERE sale_id = 'S1'"
    )

    svc = AccountingService(conn)
    history = svc.get_customer_history(1)
    timeline = history["timeline"]

    assert len(timeline) == 2
    kinds = [e["kind"] for e in timeline]
    assert kinds == ["sale", "receipt"]


def test_customer_statement_filters_period_and_computes_opening_balance():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute("INSERT INTO customers (customer_id, name) VALUES (1, 'Test')")

    # Pre-period advances
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-05-10', 50.0, 'deposit')"
    )
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-05-15', -15.0, 'applied_to_sale')"
    )

    # In-period advances
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-06-05', 20.0, 'deposit')"
    )
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-06-10', -10.0, 'applied_to_sale')"
    )

    # Post-period advance
    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-07-01', 100.0, 'deposit')"
    )

    svc = AccountingService(conn)
    statement = svc.get_customer_statement(1, start_date="2026-06-01", end_date="2026-06-30")

    # Opening balance should be 50.0 - 15.0 = 35.0
    import pytest
    assert float(statement.opening_balance) == pytest.approx(35.0)

    # Closing balance should be 35.0 + 20.0 - 10.0 = 45.0
    assert float(statement.closing_balance) == pytest.approx(45.0)

    # There should be exactly 2 entries (in-period)
    assert len(statement.entries) == 2
    assert statement.entries[0].entry_date == "2026-06-05"
    assert float(statement.entries[0].balance) == pytest.approx(55.0)
    assert statement.entries[1].entry_date == "2026-06-10"
    assert float(statement.entries[1].balance) == pytest.approx(45.0)
    conn.close()


def test_customer_statement_empty_period_keeps_nonzero_opening_balance():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    _ensure_schema(conn)

    conn.execute("INSERT INTO customers (customer_id, name) VALUES (1, 'Test')")

    conn.execute(
        "INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) "
        "VALUES (1, '2026-05-10', 50.0, 'deposit')"
    )

    svc = AccountingService(conn)
    # Filter for a period after the deposit, containing no transactions
    statement = svc.get_customer_statement(1, start_date="2026-06-01", end_date="2026-06-30")

    import pytest
    assert float(statement.opening_balance) == pytest.approx(50.0)
    assert float(statement.closing_balance) == pytest.approx(50.0)
    assert len(statement.entries) == 0
    conn.close()

