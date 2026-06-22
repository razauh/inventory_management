"""Characterization tests for customer refund reads."""

from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService


def test_customer_refund_event_matches_current_payment_row():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.executescript("""
        CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER, doc_type TEXT DEFAULT 'sale');
        CREATE TABLE sale_payments (payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id TEXT, date TEXT, amount REAL, method TEXT, clearing_state TEXT, notes TEXT);
        INSERT INTO sales (sale_id, customer_id) VALUES ('S1', 1);
        INSERT INTO sale_payments (sale_id, date, amount, method, clearing_state)
        VALUES ('S1', '2026-06-21', 100, 'Cash', 'cleared');
        INSERT INTO sale_payments (sale_id, date, amount, method, clearing_state, notes)
        VALUES ('S1', '2026-06-22', -30, 'Cash', 'cleared', 'Refund');
    """)
    svc = AccountingService(conn)
    refunds = svc.get_customer_refunds(1)
    assert len(refunds) == 1
    assert float(refunds[0].amount) == 30
    assert refunds[0].method == 'Cash'

    sale_refunds = svc.get_sale_refunds('S1')
    assert len(sale_refunds) == 1
    assert float(sale_refunds[0].amount) == 30
