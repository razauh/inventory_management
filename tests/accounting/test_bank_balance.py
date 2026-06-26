import sqlite3

import pytest

from modules.accounting import AccountingService


def _bank_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE sale_payments (
            payment_id INTEGER PRIMARY KEY,
            sale_id TEXT,
            amount REAL,
            method TEXT,
            clearing_state TEXT,
            cleared_date TEXT,
            instrument_type TEXT,
            instrument_no TEXT,
            bank_account_id INTEGER
        );
        CREATE TABLE purchase_payments (
            payment_id INTEGER PRIMARY KEY,
            purchase_id TEXT,
            amount REAL,
            method TEXT,
            clearing_state TEXT,
            cleared_date TEXT,
            instrument_type TEXT,
            instrument_no TEXT,
            bank_account_id INTEGER,
            vendor_bank_account_id INTEGER
        );
        CREATE TABLE purchase_refunds (
            refund_id INTEGER PRIMARY KEY,
            purchase_id TEXT,
            amount REAL,
            method TEXT,
            clearing_state TEXT,
            cleared_date TEXT,
            instrument_type TEXT,
            instrument_no TEXT,
            bank_account_id INTEGER,
            vendor_bank_account_id INTEGER
        );
        CREATE TABLE vendor_advances (
            tx_id INTEGER PRIMARY KEY,
            amount REAL,
            source_type TEXT,
            source_id TEXT,
            method TEXT,
            tx_date TEXT,
            cleared_date TEXT,
            clearing_state TEXT,
            instrument_type TEXT,
            instrument_no TEXT,
            bank_account_id INTEGER,
            vendor_bank_account_id INTEGER
        );
        """
    )
    return conn


def test_bank_balance_uses_cleared_inflows_and_outflows():
    conn = _bank_conn()
    conn.execute(
        "INSERT INTO sale_payments VALUES (1, 'S1', 100.0, 'Cash', 'cleared', '2026-06-21', NULL, NULL, 1)"
    )
    conn.execute(
        "INSERT INTO purchase_payments VALUES (1, 'P1', 30.0, 'Cash', 'cleared', '2026-06-21', NULL, NULL, 1, NULL)"
    )
    conn.execute(
        "INSERT INTO purchase_refunds VALUES (1, 'P1', 20.0, 'Cash', 'cleared', '2026-06-21', NULL, NULL, 1, NULL)"
    )
    conn.execute(
        "INSERT INTO vendor_advances VALUES (1, 10.0, 'deposit', 'P1', 'Cash', '2026-06-21', '2026-06-21', 'cleared', NULL, NULL, 1, NULL)"
    )

    balance = AccountingService(conn).get_bank_balance(1)

    assert float(balance.balance) == pytest.approx(80.0)


def test_bank_balance_ignores_pending_and_bounced_rows():
    conn = _bank_conn()
    conn.execute(
        "INSERT INTO sale_payments VALUES (1, 'S1', 100.0, 'Cash', 'pending', NULL, NULL, NULL, 1)"
    )
    conn.execute(
        "INSERT INTO sale_payments VALUES (2, 'S1', 75.0, 'Cash', 'bounced', NULL, NULL, NULL, 1)"
    )
    conn.execute(
        "INSERT INTO purchase_payments VALUES (1, 'P1', 30.0, 'Cash', 'pending', NULL, NULL, NULL, 1, NULL)"
    )

    balance = AccountingService(conn).get_bank_balance(1)

    assert float(balance.balance) == pytest.approx(0.0)


def test_missing_bank_account_returns_zero():
    conn = _bank_conn()
    conn.execute(
        "INSERT INTO sale_payments VALUES (1, 'S1', 100.0, 'Cash', 'cleared', '2026-06-21', NULL, NULL, 1)"
    )

    balance = AccountingService(conn).get_bank_balance(999)

    assert balance.bank_account_id == 999
    assert float(balance.balance) == pytest.approx(0.0)
