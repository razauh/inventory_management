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


def test_validate_expense_category_input():
    service = AccountingService(sqlite3.connect(":memory:"))

    # Blank name validation
    with pytest.raises(ValueError, match="Name cannot be empty"):
        service.validate_expense_category_input("")

    with pytest.raises(ValueError, match="Name cannot be empty"):
        service.validate_expense_category_input("   ")


def test_record_expense_category_create_event(db_conn):
    service = AccountingService(db_conn)

    # Creation
    cat_id = service.record_expense_category_create_event("Rent")
    assert cat_id > 0

    # Read back to verify
    row = db_conn.execute("SELECT * FROM expense_categories WHERE category_id = ?", (cat_id,)).fetchone()
    assert row["name"] == "Rent"

    # Duplicate name raises IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        service.record_expense_category_create_event("Rent")


def test_record_expense_category_update_event(db_conn):
    service = AccountingService(db_conn)
    cat_id = service.record_expense_category_create_event("Rent")

    # Update
    service.record_expense_category_update_event(cat_id, "Office Rent")

    row = db_conn.execute("SELECT * FROM expense_categories WHERE category_id = ?", (cat_id,)).fetchone()
    assert row["name"] == "Office Rent"

    # Non-existent category update raises ValueError
    with pytest.raises(ValueError, match="Category with ID 9999 not found"):
        service.record_expense_category_update_event(9999, "Utilities")


def test_record_expense_category_delete_event(db_conn):
    service = AccountingService(db_conn)
    cat_id = service.record_expense_category_create_event("Rent")

    # Delete
    service.record_expense_category_delete_event(cat_id)

    row = db_conn.execute("SELECT * FROM expense_categories WHERE category_id = ?", (cat_id,)).fetchone()
    assert row is None

    # Non-existent category delete raises ValueError
    with pytest.raises(ValueError, match="Category with ID 9999 not found"):
        service.record_expense_category_delete_event(9999)


def test_record_expense_category_delete_blocked(db_conn):
    service = AccountingService(db_conn)
    cat_id = service.record_expense_category_create_event("Rent")

    # Add expense referencing category
    service.record_expense_create_event(
        description="June Rent",
        amount=1200.0,
        date="2026-06-01",
        category_id=cat_id,
    )

    # Deleting category is blocked by FK constraint -> raises ValueError
    with pytest.raises(ValueError, match="Cannot delete a category that is used by existing expenses"):
        service.record_expense_category_delete_event(cat_id)


def test_expenses_repo_category_delegation(db_conn):
    repo = ExpensesRepo(db_conn)

    # Create category
    cat_id = repo.create_category("Rent")
    assert cat_id > 0

    # Update category
    repo.update_category(cat_id, "Office Rent")

    cats = repo.list_categories()
    assert any(c.category_id == cat_id and c.name == "Office Rent" for c in cats)

    # Delete category
    repo.delete_category(cat_id)
    cats = repo.list_categories()
    assert not any(c.category_id == cat_id for c in cats)

    # Validation errors map to DomainError
    with pytest.raises(DomainError, match="Name cannot be empty"):
        repo.create_category("")

    with pytest.raises(DomainError, match="Name cannot be empty"):
        repo.update_category(999, "  ")

    # Non-existent maps to DomainError
    with pytest.raises(DomainError, match="Category with ID 9999 not found"):
        repo.update_category(9999, "Utilities")

    # Delete blocked maps to DomainError
    cat_id2 = repo.create_category("Utilities")
    repo.create_expense("Electricity", 150.0, "2026-06-23", cat_id2)
    with pytest.raises(DomainError, match="Cannot delete a category that is used by existing expenses"):
        repo.delete_category(cat_id2)
