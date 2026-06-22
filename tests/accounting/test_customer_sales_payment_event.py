"""Characterization tests for payment write events."""

from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import (
    AccountingService,
    CustomerPaymentPayload,
    CustomerPaymentResult,
)


def test_record_customer_payment_preserves_sale_payment_row():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sale_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT, date TEXT, amount REAL, method TEXT,
            bank_account_id INTEGER, instrument_type TEXT, instrument_no TEXT,
            instrument_date TEXT, deposited_date TEXT, cleared_date TEXT,
            clearing_state TEXT, ref_no TEXT, notes TEXT, created_by INTEGER,
            overpayment_converted INTEGER DEFAULT 0, converted_to_credit REAL DEFAULT 0
        );
        CREATE TABLE customer_advances (
            tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, tx_date TEXT, amount REAL,
            source_type TEXT, source_id TEXT, notes TEXT, created_by INTEGER
        );
        CREATE TABLE sales (
            sale_id TEXT PRIMARY KEY, customer_id INTEGER, date TEXT,
            total_amount REAL, doc_type TEXT DEFAULT 'sale'
        );
        CREATE TABLE sale_receivable_totals (
            sale_id TEXT PRIMARY KEY, canonical_total_amount REAL,
            paid_amount REAL, advance_payment_applied REAL, remaining_due REAL
        );
        INSERT INTO sales (sale_id, customer_id, date, total_amount) VALUES ('S1', 1, '2026-06-21', 100);
        INSERT INTO sale_receivable_totals (sale_id, canonical_total_amount) VALUES ('S1', 100);
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT);
        INSERT OR IGNORE INTO customers (customer_id, name) VALUES (1, 'Test');
    """)

    svc = AccountingService(conn)
    payload = CustomerPaymentPayload(
        sale_id='S1', customer_id=1, amount=Decimal('50'),
        method='Cash', date='2026-06-22', clearing_state='cleared',
    )
    result = svc.record_customer_payment_event(payload)
    assert isinstance(result, CustomerPaymentResult)
    assert result.payment_id > 0

    row = conn.execute(
        "SELECT * FROM sale_payments WHERE payment_id = ?",
        (result.payment_id,),
    ).fetchone()
    assert float(row["amount"]) == 50.0
    assert row["method"] == "Cash"
    assert row["clearing_state"] == "cleared"
