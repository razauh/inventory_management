"""Characterization tests for customer credit grant events."""

import pytest
from decimal import Decimal
from sqlite3 import connect, Row as SqliteRow

from modules.accounting import AccountingService, CustomerCreditPayload


def test_customer_deposit_event_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute("CREATE TABLE customer_advances ("
        "tx_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, tx_date TEXT, "
        "amount REAL, source_type TEXT, source_id TEXT, method TEXT, "
        "bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER)")
    conn.execute("CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS "
        "SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance "
        "FROM customer_advances GROUP BY customer_id")

    svc = AccountingService(conn)
    payload = CustomerCreditPayload(
        customer_id=1, amount=Decimal("100"), source_type="deposit",
        date="2026-06-21", method="Cash")
    result = svc.record_customer_credit_event(payload)
    assert result.tx_id > 0
    assert result.source_type == "deposit"

    row = conn.execute("SELECT * FROM customer_advances WHERE tx_id = ?", (result.tx_id,)).fetchone()
    assert float(row["amount"]) == 100.0
    assert row["source_type"] == "deposit"


def test_customer_return_credit_event_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute("CREATE TABLE customer_advances ("
        "tx_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, tx_date TEXT, "
        "amount REAL, source_type TEXT, source_id TEXT, method TEXT, "
        "bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER)")
    conn.execute("CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS "
        "SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance "
        "FROM customer_advances GROUP BY customer_id")

    svc = AccountingService(conn)
    payload = CustomerCreditPayload(
        customer_id=1, amount=Decimal("50"), source_type="return_credit",
        source_id="S1", date="2026-06-22")
    result = svc.record_customer_credit_event(payload)
    assert result.source_type == "return_credit"

    row = conn.execute("SELECT * FROM customer_advances WHERE tx_id = ?", (result.tx_id,)).fetchone()
    assert float(row["amount"]) == 50.0
    assert row["source_type"] == "return_credit"
    assert row["source_id"] == "S1"


def test_customer_credit_ledger_matches_repo():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute("CREATE TABLE customer_advances ("
        "tx_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, tx_date TEXT, "
        "amount REAL, source_type TEXT, source_id TEXT, method TEXT, "
        "bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER)")
    conn.execute("CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS "
        "SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance "
        "FROM customer_advances GROUP BY customer_id")

    conn.execute("INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) VALUES (1, '2026-06-21', 100, 'deposit')")
    conn.execute("INSERT INTO customer_advances (customer_id, tx_date, amount, source_type) VALUES (1, '2026-06-22', -30, 'applied_to_sale')")

    svc = AccountingService(conn)
    rows = svc.list_customer_credit_ledger(1)
    assert len(rows) == 2
    assert rows[0].source_type == "deposit"
    assert float(rows[0].amount) == 100.0
    assert rows[1].source_type == "applied_to_sale"
    assert float(rows[1].amount) == -30.0


def test_customer_credit_event_validation_matches_receipt_rules():
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute("CREATE TABLE customer_advances ("
        "tx_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, tx_date TEXT, "
        "amount REAL, source_type TEXT, source_id TEXT, method TEXT, "
        "bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER)")
    # Also need company_bank_accounts table for the active bank account check
    conn.execute("CREATE TABLE company_bank_accounts ("
        "account_id INTEGER PRIMARY KEY AUTOINCREMENT, account_name TEXT, is_active INTEGER)")
    conn.execute("INSERT INTO company_bank_accounts (account_name, is_active) VALUES ('Co Bank', 1)")

    svc = AccountingService(conn)

    # 1. Non-cash method without bank account
    payload_no_bank = CustomerCreditPayload(
        customer_id=1, amount=Decimal("100"), source_type="deposit",
        date="2026-06-21", method="Bank Transfer", bank_account_id=None, reference_no="REF123")
    with pytest.raises(ValueError, match="A company bank account is required for this method"):
        svc.record_customer_credit_event(payload_no_bank)

    # 2. Non-cash method without reference
    payload_no_ref = CustomerCreditPayload(
        customer_id=1, amount=Decimal("100"), source_type="deposit",
        date="2026-06-21", method="Bank Transfer", bank_account_id=1, reference_no=None)
    with pytest.raises(ValueError, match="A reference is required for non-cash customer credit"):
        svc.record_customer_credit_event(payload_no_ref)

    # 3. Cash with bank account
    # Wait, the repo rule says:
    # "if method != 'Cash' and not (reference_no or '').strip(): raise ValueError(...)"
    # But does the repo rule block cash with bank account?
    # Let's check CustomerAdvancesRepo:
    # "if method in {'Bank Transfer', 'Card', 'Cheque'} and bank_account_id is None: raise ValueError..."
    # "if method != 'Cash' and not (reference_no or '').strip(): raise ValueError..."
    # So the repo does not raise an error if method is Cash and bank_account_id is not None.
    # Therefore, we only assert what the repo asserts.

    conn.close()


def test_non_cash_customer_credit_requires_reference_and_bank_if_policy_requires_it():
    from database.repositories.customer_advances_repo import CustomerAdvancesRepo
    conn = connect(":memory:")
    conn.row_factory = SqliteRow
    conn.execute("CREATE TABLE customer_advances ("
        "tx_id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, tx_date TEXT, "
        "amount REAL, source_type TEXT, source_id TEXT, method TEXT, "
        "bank_account_id INTEGER, reference_no TEXT, notes TEXT, created_by INTEGER)")
    conn.execute("CREATE TABLE company_bank_accounts ("
        "account_id INTEGER PRIMARY KEY AUTOINCREMENT, account_name TEXT, is_active INTEGER)")
    conn.execute("INSERT INTO company_bank_accounts (account_name, is_active) VALUES ('Co Bank', 1)")
    conn.execute("CREATE VIEW IF NOT EXISTS v_customer_advance_balance AS "
        "SELECT customer_id, COALESCE(SUM(amount), 0.0) AS balance "
        "FROM customer_advances GROUP BY customer_id")

    repo = CustomerAdvancesRepo(conn)

    # Calling grant_credit with Bank Transfer and no bank account should raise ValueError
    with pytest.raises(ValueError, match="A company bank account is required for this method"):
        repo.grant_credit(customer_id=1, amount=100.0, method="Bank Transfer", bank_account_id=None, reference_no="REF123")

    # Calling grant_credit with Bank Transfer and no reference should raise ValueError
    with pytest.raises(ValueError, match="A reference is required for non-cash customer credit"):
        repo.grant_credit(customer_id=1, amount=100.0, method="Bank Transfer", bank_account_id=1, reference_no="")
    conn.close()

