import sqlite3

from inventory_management.database.repositories.customers_repo import CustomersRepo
from inventory_management.database.repositories.expenses_repo import ExpensesRepo
from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.database.schema import SQL


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    return conn


def test_customers_repo_create_preserves_outer_transaction_and_commits_standalone():
    conn = make_db()
    repo = CustomersRepo(conn)

    conn.execute("BEGIN")
    customer_id = repo.create("Customer A", "123", "Street")
    assert conn.in_transaction is True
    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) AS c FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()["c"] == 0

    customer_id = repo.create("Customer B", "456", "Road")
    assert conn.in_transaction is False
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM customers WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()["c"] == 1
    conn.close()


def test_vendors_repo_update_preserves_outer_transaction_and_commits_standalone():
    conn = make_db()
    repo = VendorsRepo(conn)
    vendor_id = repo.create("Vendor A", "123", None)

    conn.execute("BEGIN")
    repo.update(vendor_id, "Vendor Changed", "999", "Addr")
    assert conn.in_transaction is True
    conn.rollback()

    row = conn.execute(
        "SELECT name, contact_info, address FROM vendors WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()
    assert dict(row) == {
        "name": "Vendor A",
        "contact_info": "123",
        "address": None,
    }

    repo.update(vendor_id, "Vendor Final", "555", "Addr 2")
    assert conn.in_transaction is False
    row = conn.execute(
        "SELECT name, contact_info, address FROM vendors WHERE vendor_id = ?",
        (vendor_id,),
    ).fetchone()
    assert dict(row) == {
        "name": "Vendor Final",
        "contact_info": "555",
        "address": "Addr 2",
    }
    conn.close()


def test_expenses_repo_delete_category_preserves_outer_transaction_and_commits_standalone():
    conn = make_db()
    repo = ExpensesRepo(conn)
    category_id = repo.create_category("Office")

    conn.execute("BEGIN")
    repo.delete_category(category_id)
    assert conn.in_transaction is True
    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) AS c FROM expense_categories WHERE category_id = ?",
        (category_id,),
    ).fetchone()["c"] == 1

    repo.delete_category(category_id)
    assert conn.in_transaction is False
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM expense_categories WHERE category_id = ?",
        (category_id,),
    ).fetchone()["c"] == 0
    conn.close()
