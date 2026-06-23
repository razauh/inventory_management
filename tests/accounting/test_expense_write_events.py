import sqlite3
import pytest
from database.schema import SQL
from database.repositories.expenses_repo import ExpensesRepo, DomainError
from modules.accounting import AccountingService


@pytest.fixture()
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    try:
        yield conn
    finally:
        conn.close()


def test_validate_expense_input():
    service = AccountingService(sqlite3.connect(":memory:"))

    # Empty description
    with pytest.raises(ValueError, match="Description cannot be empty"):
        service.validate_expense_input("", 100.0, "2026-06-23", None)

    with pytest.raises(ValueError, match="Description cannot be empty"):
        service.validate_expense_input("   ", 100.0, "2026-06-23", None)

    # Invalid amount
    with pytest.raises(ValueError, match="Amount must be a finite positive number"):
        service.validate_expense_input("Coffee", 0.0, "2026-06-23", None)

    with pytest.raises(ValueError, match="Amount must be a finite positive number"):
        service.validate_expense_input("Coffee", -5.0, "2026-06-23", None)

    with pytest.raises(ValueError, match="Amount must be a finite positive number"):
        service.validate_expense_input("Coffee", float("nan"), "2026-06-23", None)

    # Invalid date
    with pytest.raises(ValueError, match="Date cannot be empty"):
        service.validate_expense_input("Coffee", 10.0, "", None)

    with pytest.raises(ValueError, match="Date must be in YYYY-MM-DD format"):
        service.validate_expense_input("Coffee", 10.0, "2026/06/23", None)

    with pytest.raises(ValueError, match="Date must be in YYYY-MM-DD format"):
        service.validate_expense_input("Coffee", 10.0, "not-a-date", None)


def test_record_expense_create_event(db_conn):
    service = AccountingService(db_conn)

    expense_id = service.record_expense_create_event(
        description="Office paper",
        amount=25.50,
        date="2026-06-23",
        category_id=None,
    )
    assert expense_id > 0

    # Read back to verify
    row = db_conn.execute("SELECT * FROM expenses WHERE expense_id = ?", (expense_id,)).fetchone()
    assert row["description"] == "Office paper"
    assert float(row["amount"]) == 25.50
    assert row["date"] == "2026-06-23"
    assert row["category_id"] is None


def test_record_expense_update_event(db_conn):
    service = AccountingService(db_conn)

    expense_id = service.record_expense_create_event(
        description="Office paper",
        amount=25.50,
        date="2026-06-23",
        category_id=None,
    )

    # Update
    service.record_expense_update_event(
        expense_id=expense_id,
        description="Better paper",
        amount=30.00,
        date="2026-06-24",
        category_id=None,
    )

    # Read back
    row = db_conn.execute("SELECT * FROM expenses WHERE expense_id = ?", (expense_id,)).fetchone()
    assert row["description"] == "Better paper"
    assert float(row["amount"]) == 30.00
    assert row["date"] == "2026-06-24"

    # Non-existent update raises ValueError
    with pytest.raises(ValueError, match="Expense with ID 9999 not found"):
        service.record_expense_update_event(9999, "Supplies", 10.0, "2026-06-23", None)


def test_record_expense_delete_event(db_conn):
    service = AccountingService(db_conn)

    expense_id = service.record_expense_create_event(
        description="Office paper",
        amount=25.50,
        date="2026-06-23",
        category_id=None,
    )

    # Delete
    service.record_expense_delete_event(expense_id)

    # Verify deleted
    row = db_conn.execute("SELECT * FROM expenses WHERE expense_id = ?", (expense_id,)).fetchone()
    assert row is None

    # Non-existent delete raises ValueError
    with pytest.raises(ValueError, match="Expense with ID 9999 not found"):
        service.record_expense_delete_event(9999)


def test_expenses_repo_write_delegation(db_conn):
    repo = ExpensesRepo(db_conn)

    # Create via repo
    expense_id = repo.create_expense(
        description="Lunch",
        amount=15.00,
        date="2026-06-23",
        category_id=None,
    )
    assert expense_id > 0

    # Update via repo
    repo.update_expense(
        expense_id=expense_id,
        description="Team lunch",
        amount=18.50,
        date="2026-06-23",
        category_id=None,
    )

    # Check update
    exp = repo.get_expense(expense_id)
    assert exp.description == "Team lunch"
    assert exp.amount == 18.50

    # Delete via repo
    repo.delete_expense(expense_id)
    assert repo.get_expense(expense_id) is None

    # Validation errors map to DomainError
    with pytest.raises(DomainError, match="Description cannot be empty"):
        repo.create_expense("", 15.0, "2026-06-23", None)

    with pytest.raises(DomainError, match="Amount must be a finite positive number"):
        repo.create_expense("Lunch", -5.0, "2026-06-23", None)

    with pytest.raises(DomainError, match="Date must be in YYYY-MM-DD format"):
        repo.create_expense("Lunch", 15.0, "2026/06/23", None)


def test_expense_model_no_cash_link_is_documented_behavior(db_conn):
    service = AccountingService(db_conn)

    # Record initial counts/balances
    initial_bank_ledger = service.get_bank_ledger()
    initial_vendor_movements = service.get_vendor_cash_movements()
    initial_customer_movements = service.get_customer_cash_movements()

    # Record a new expense
    expense_id = service.record_expense_create_event(
        description="Office catering",
        amount=150.00,
        date="2026-06-23",
        category_id=None,
    )
    assert expense_id > 0

    # Assert that bank ledger, customer/vendor cash movements are completely unaffected
    assert service.get_bank_ledger() == initial_bank_ledger
    assert service.get_vendor_cash_movements() == initial_vendor_movements
    assert service.get_customer_cash_movements() == initial_customer_movements

    # Update the expense
    service.record_expense_update_event(
        expense_id=expense_id,
        description="Office catering (updated)",
        amount=200.00,
        date="2026-06-23",
        category_id=None,
    )

    # Check again
    assert service.get_bank_ledger() == initial_bank_ledger
    assert service.get_vendor_cash_movements() == initial_vendor_movements
    assert service.get_customer_cash_movements() == initial_customer_movements

    # Delete the expense
    service.record_expense_delete_event(expense_id)

    # Check again
    assert service.get_bank_ledger() == initial_bank_ledger
    assert service.get_vendor_cash_movements() == initial_vendor_movements
    assert service.get_customer_cash_movements() == initial_customer_movements

