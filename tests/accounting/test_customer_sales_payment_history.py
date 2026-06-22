"""Characterization tests for payment history reads."""

from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService, SalePaymentRow


def test_sale_payment_history_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute(
        "CREATE TABLE sale_payments ("
        "payment_id INTEGER PRIMARY KEY, sale_id TEXT, date TEXT, "
        "amount REAL, method TEXT, clearing_state TEXT, "
        "bank_account_id INTEGER, instrument_type TEXT, instrument_no TEXT, "
        "instrument_date TEXT, deposited_date TEXT, cleared_date TEXT, "
        "ref_no TEXT, notes TEXT, created_by INTEGER, bank_account_label TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO sale_payments (payment_id, sale_id, date, amount, method, clearing_state) "
        "VALUES (1, 'S1', '2026-06-21', 100.0, 'Cash', 'cleared')"
    )
    conn.execute(
        "INSERT INTO sale_payments (payment_id, sale_id, date, amount, method, clearing_state) "
        "VALUES (2, 'S1', '2026-06-22', -20.0, 'Cash', 'cleared')"
    )

    svc = AccountingService(conn)
    rows = svc.get_sale_payment_history('S1')
    assert len(rows) == 2
    assert rows[0].payment_id == 1
    assert float(rows[0].amount) == 100.0
    assert rows[0].method == 'Cash'
    assert rows[1].payment_id == 2
    assert float(rows[1].amount) == -20.0


def test_latest_sale_payment_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute(
        "CREATE TABLE sale_payments ("
        "payment_id INTEGER PRIMARY KEY, sale_id TEXT, date TEXT, "
        "amount REAL, method TEXT, clearing_state TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO sale_payments (payment_id, sale_id, date, amount, method) "
        "VALUES (1, 'S1', '2026-06-21', 50.0, 'Cash')"
    )
    conn.execute(
        "INSERT INTO sale_payments (payment_id, sale_id, date, amount, method) "
        "VALUES (2, 'S1', '2026-06-22', 70.0, 'Bank Transfer')"
    )

    svc = AccountingService(conn)
    latest = svc.get_latest_sale_payment('S1')
    assert latest is not None
    assert latest.payment_id == 2
    assert float(latest.amount) == 70.0
    assert latest.method == 'Bank Transfer'

    none_result = svc.get_latest_sale_payment('NONEXISTENT')
    assert none_result is None


def test_customer_payment_history_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute(
        "CREATE TABLE sales (sale_id TEXT PRIMARY KEY, customer_id INTEGER, doc_type TEXT)"
    )
    conn.execute(
        "CREATE TABLE sale_payments ("
        "payment_id INTEGER PRIMARY KEY, sale_id TEXT, date TEXT, "
        "amount REAL, method TEXT, clearing_state TEXT"
        ")"
    )
    conn.execute("INSERT INTO sales VALUES ('S1', 1, 'sale')")
    conn.execute("INSERT INTO sales VALUES ('S2', 1, 'sale')")
    conn.execute(
        "INSERT INTO sale_payments (payment_id, sale_id, date, amount, method) "
        "VALUES (1, 'S1', '2026-06-21', 50.0, 'Cash')"
    )
    conn.execute(
        "INSERT INTO sale_payments (payment_id, sale_id, date, amount, method) "
        "VALUES (2, 'S2', '2026-06-22', 100.0, 'Cheque')"
    )

    svc = AccountingService(conn)
    rows = svc.get_customer_payment_history(1)
    assert len(rows) == 2
