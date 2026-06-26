import sqlite3

import pytest

from modules.accounting import AccountingService


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _vendor_schema(conn):
    conn.executescript(
        """
        CREATE TABLE vendors (vendor_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE purchases (
            purchase_id INTEGER PRIMARY KEY,
            vendor_id INTEGER,
            total_amount REAL,
            paid_amount REAL DEFAULT 0,
            advance_payment_applied REAL DEFAULT 0
        );
        CREATE TABLE purchase_detailed_totals (
            purchase_id INTEGER PRIMARY KEY,
            calculated_total_amount REAL
        );
        CREATE TABLE vendor_advances (
            tx_id INTEGER PRIMARY KEY,
            vendor_id INTEGER,
            amount REAL
        );
        CREATE VIEW v_vendor_advance_balance AS
            SELECT vendor_id, COALESCE(SUM(amount), 0.0) AS balance
            FROM vendor_advances
            GROUP BY vendor_id;
        """
    )


def _customer_schema(conn):
    conn.executescript(
        """
        CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE sales (
            sale_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            doc_type TEXT DEFAULT 'sale'
        );
        CREATE TABLE sale_receivable_totals (
            sale_id INTEGER PRIMARY KEY,
            remaining_due REAL
        );
        CREATE TABLE customer_advances (
            tx_id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            amount REAL
        );
        CREATE VIEW v_customer_advance_balance AS
            SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance
            FROM customer_advances
            GROUP BY customer_id;
        """
    )


def test_empty_and_invalid_vendor_customer_balances_return_zero():
    conn = _conn()
    _vendor_schema(conn)
    _customer_schema(conn)
    service = AccountingService(conn)

    assert service.get_vendor_balance(999).balance == 0
    assert service.get_customer_balance(999).balance == 0


def test_vendor_balance_positive_means_vendor_owes_us():
    conn = _conn()
    _vendor_schema(conn)
    conn.execute("INSERT INTO vendors VALUES (1, 'Vendor')")
    conn.execute(
        "INSERT INTO purchases VALUES (1, 1, 100.0, 40.0, 0.0)"
    )
    conn.execute("INSERT INTO purchase_detailed_totals VALUES (1, 100.0)")
    conn.execute("INSERT INTO vendor_advances VALUES (1, 1, 80.0)")

    balance = AccountingService(conn).get_vendor_balance(1)

    assert float(balance.balance) == pytest.approx(20.0)


def test_vendor_balance_negative_means_we_owe_vendor():
    conn = _conn()
    _vendor_schema(conn)
    conn.execute("INSERT INTO vendors VALUES (1, 'Vendor')")
    conn.execute(
        "INSERT INTO purchases VALUES (1, 1, 100.0, 25.0, 0.0)"
    )
    conn.execute("INSERT INTO purchase_detailed_totals VALUES (1, 100.0)")
    conn.execute("INSERT INTO vendor_advances VALUES (1, 1, 10.0)")

    balance = AccountingService(conn).get_vendor_balance(1)

    assert float(balance.balance) == pytest.approx(-65.0)


def test_vendor_full_payment_returns_zero_balance():
    conn = _conn()
    _vendor_schema(conn)
    conn.execute("INSERT INTO vendors VALUES (1, 'Vendor')")
    conn.execute(
        "INSERT INTO purchases VALUES (1, 1, 100.0, 100.0, 0.0)"
    )
    conn.execute("INSERT INTO purchase_detailed_totals VALUES (1, 100.0)")

    balance = AccountingService(conn).get_vendor_balance(1)

    assert float(balance.balance) == pytest.approx(0.0)


def test_customer_balance_positive_means_we_owe_customer():
    conn = _conn()
    _customer_schema(conn)
    conn.execute("INSERT INTO customers VALUES (1, 'Customer')")
    conn.execute("INSERT INTO sales VALUES (1, 1, 'sale')")
    conn.execute("INSERT INTO sale_receivable_totals VALUES (1, 50.0)")
    conn.execute("INSERT INTO customer_advances VALUES (1, 1, 80.0)")

    balance = AccountingService(conn).get_customer_balance(1)

    assert float(balance.balance) == pytest.approx(30.0)


def test_customer_balance_negative_means_customer_owes_us():
    conn = _conn()
    _customer_schema(conn)
    conn.execute("INSERT INTO customers VALUES (1, 'Customer')")
    conn.execute("INSERT INTO sales VALUES (1, 1, 'sale')")
    conn.execute("INSERT INTO sale_receivable_totals VALUES (1, 70.0)")
    conn.execute("INSERT INTO customer_advances VALUES (1, 1, 20.0)")

    balance = AccountingService(conn).get_customer_balance(1)

    assert float(balance.balance) == pytest.approx(-50.0)


def test_customer_full_payment_returns_zero_balance():
    conn = _conn()
    _customer_schema(conn)
    conn.execute("INSERT INTO customers VALUES (1, 'Customer')")
    conn.execute("INSERT INTO sales VALUES (1, 1, 'sale')")
    conn.execute("INSERT INTO sale_receivable_totals VALUES (1, 0.0)")

    balance = AccountingService(conn).get_customer_balance(1)

    assert float(balance.balance) == pytest.approx(0.0)
