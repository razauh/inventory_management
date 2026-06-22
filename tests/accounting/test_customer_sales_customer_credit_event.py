"""Characterization tests for customer credit grant events."""

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
