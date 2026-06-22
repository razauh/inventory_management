"""Characterization tests for credit application events."""

from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import (
    AccountingService,
    CustomerCreditApplicationPayload,
)


def test_customer_credit_application_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER,
            total_amount REAL, paid_amount REAL DEFAULT 0,
            order_discount REAL DEFAULT 0, doc_type TEXT DEFAULT 'sale');
        CREATE TABLE customer_advances (tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT, method TEXT,
            bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER);
        CREATE VIEW sale_detailed_totals AS SELECT sale_id, 0 AS order_discount,
            0 AS subtotal_before_order_discount, total_amount AS calculated_total_amount,
            0 AS returned_value, MAX(0,total_amount) AS net_total_amount FROM sales;
        CREATE VIEW sale_receivable_totals AS SELECT sale_id,
            MAX(0,net_total_amount) AS canonical_total_amount, 0 AS paid_amount,
            0 AS advance_payment_applied,
            MAX(0,net_total_amount) AS remaining_due
            FROM sale_detailed_totals;
        INSERT INTO sales (sale_id, customer_id, total_amount) VALUES ('S1', 1, 100);
    """)

    svc = AccountingService(conn)
    payload = CustomerCreditApplicationPayload(
        customer_id=1, sale_id='S1', amount=Decimal('40'), date='2026-06-22')
    result = svc.record_customer_credit_application_event(payload)
    assert result.tx_id > 0
    assert result.sale_id == 'S1'

    row = conn.execute("SELECT * FROM customer_advances WHERE tx_id = ?", (result.tx_id,)).fetchone()
    assert float(row["amount"]) == -40.0
    assert row["source_type"] == "applied_to_sale"


def test_customer_credit_application_preserves_due_cap():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER,
            total_amount REAL, paid_amount REAL DEFAULT 0,
            order_discount REAL DEFAULT 0, doc_type TEXT DEFAULT 'sale');
        CREATE TABLE customer_advances (tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT, method TEXT,
            bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER);
        CREATE VIEW sale_detailed_totals AS SELECT sale_id, 0 AS order_discount,
            0 AS subtotal_before_order_discount, total_amount AS calculated_total_amount,
            0 AS returned_value, MAX(0,total_amount) AS net_total_amount FROM sales;
        CREATE VIEW sale_receivable_totals AS SELECT sale_id,
            MAX(0,net_total_amount) AS canonical_total_amount, 0 AS paid_amount,
            0 AS advance_payment_applied,
            MAX(0,net_total_amount) AS remaining_due
            FROM sale_detailed_totals;
        INSERT INTO sales (sale_id, customer_id, total_amount) VALUES ('S1', 1, 100);
    """)

    svc = AccountingService(conn)
    payload = CustomerCreditApplicationPayload(
        customer_id=1, sale_id='S1', amount=Decimal('200'), date='2026-06-22')
    try:
        svc.record_customer_credit_application_event(payload)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "remaining due" in str(e).lower()


def test_customer_credit_application_rejects_bad_sale():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER,
            total_amount REAL, paid_amount REAL DEFAULT 0,
            order_discount REAL DEFAULT 0, doc_type TEXT DEFAULT 'quotation');
        CREATE TABLE customer_advances (tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT, method TEXT,
            bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER);
        CREATE VIEW sale_detailed_totals AS SELECT sale_id, 0 AS order_discount,
            0 AS subtotal_before_order_discount, total_amount AS calculated_total_amount,
            0 AS returned_value, MAX(0,total_amount) AS net_total_amount FROM sales;
        CREATE VIEW sale_receivable_totals AS SELECT sale_id,
            MAX(0,net_total_amount) AS canonical_total_amount, 0 AS paid_amount,
            0 AS advance_payment_applied,
            MAX(0,net_total_amount) AS remaining_due
            FROM sale_detailed_totals;
        INSERT INTO sales (sale_id, customer_id, total_amount, doc_type) VALUES ('Q1', 1, 100, 'quotation');
    """)

    svc = AccountingService(conn)
    payload = CustomerCreditApplicationPayload(
        customer_id=1, sale_id='Q1', amount=Decimal('10'), date='2026-06-22')
    try:
        svc.record_customer_credit_application_event(payload)
        assert False, "expected ValueError"
    except ValueError as e:
        assert "quotation" in str(e).lower()
