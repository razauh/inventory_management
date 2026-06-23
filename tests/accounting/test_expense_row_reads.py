import sqlite3
from decimal import Decimal
import pytest
from database.schema import SQL
from modules.accounting import AccountingService


@pytest.fixture()
def expense_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    # Insert test categories
    cat_id1 = conn.execute(
        "INSERT INTO expense_categories (name) VALUES ('Utilities')"
    ).lastrowid
    cat_id2 = conn.execute(
        "INSERT INTO expense_categories (name) VALUES ('Office Supplies')"
    ).lastrowid

    # Insert test expenses
    # Columns: description, amount, date, category_id
    conn.execute(
        "INSERT INTO expenses (description, amount, date, category_id) VALUES (?, ?, ?, ?)",
        ("Electric bill", 120.50, "2026-06-10", cat_id1)
    )
    conn.execute(
        "INSERT INTO expenses (description, amount, date, category_id) VALUES (?, ?, ?, ?)",
        ("Paper and pens", 45.00, "2026-06-15", cat_id2)
    )
    conn.execute(
        "INSERT INTO expenses (description, amount, date, category_id) VALUES (?, ?, ?, ?)",
        ("Internet bill", 80.00, "2026-06-20", cat_id1)
    )
    conn.execute(
        "INSERT INTO expenses (description, amount, date, category_id) VALUES (?, ?, ?, ?)",
        ("Coffee", 15.75, "2026-06-20", None)  # Uncategorized
    )

    try:
        yield conn, {
            "utilities": int(cat_id1),
            "supplies": int(cat_id2),
        }
    finally:
        conn.close()


def test_get_expense_financial_summary(expense_db):
    conn, cats = expense_db
    service = AccountingService(conn)

    # Find the internet bill id
    row = conn.execute("SELECT expense_id FROM expenses WHERE description = 'Internet bill'").fetchone()
    exp_id = row["expense_id"]

    summary = service.get_expense_financial_summary(exp_id)
    assert summary is not None
    assert summary.expense_id == exp_id
    assert summary.description == "Internet bill"
    assert summary.amount == Decimal("80.00")
    assert summary.date == "2026-06-20"
    assert summary.category_id == cats["utilities"]
    assert summary.category_name == "Utilities"

    # Non-existent ID returns None
    assert service.get_expense_financial_summary(99999) is None


def test_list_expense_rows_all(expense_db):
    conn, cats = expense_db
    service = AccountingService(conn)

    rows = service.list_expense_rows()
    assert len(rows) == 4
    # Ordered by date DESC, then expense_id DESC
    # "Internet bill" (2026-06-20) and "Coffee" (2026-06-20)
    # The last inserted on the same day comes first because of DESC id
    assert rows[0].description == "Coffee"
    assert rows[1].description == "Internet bill"
    assert rows[2].description == "Paper and pens"
    assert rows[3].description == "Electric bill"


def test_list_expense_rows_filter_query(expense_db):
    conn, cats = expense_db
    service = AccountingService(conn)

    rows = service.list_expense_rows(query="bill")
    assert len(rows) == 2
    assert {r.description for r in rows} == {"Electric bill", "Internet bill"}


def test_list_expense_rows_filter_date(expense_db):
    conn, cats = expense_db
    service = AccountingService(conn)

    rows = service.list_expense_rows(date="2026-06-20")
    assert len(rows) == 2
    assert {r.description for r in rows} == {"Internet bill", "Coffee"}


def test_list_expense_rows_filter_date_range(expense_db):
    conn, cats = expense_db
    service = AccountingService(conn)

    rows = service.list_expense_rows(date_from="2026-06-11", date_to="2026-06-20")
    assert len(rows) == 3
    assert {r.description for r in rows} == {"Internet bill", "Coffee", "Paper and pens"}


def test_list_expense_rows_filter_category(expense_db):
    conn, cats = expense_db
    service = AccountingService(conn)

    # Filter by Utilities
    rows = service.list_expense_rows(category_id=cats["utilities"])
    assert len(rows) == 2
    assert {r.description for r in rows} == {"Electric bill", "Internet bill"}

    # Filter by Uncategorized (category_id = 0)
    rows = service.list_expense_rows(category_id=0)
    assert len(rows) == 1
    assert rows[0].description == "Coffee"


def test_list_expense_rows_filter_amount_range(expense_db):
    conn, cats = expense_db
    service = AccountingService(conn)

    rows = service.list_expense_rows(amount_min=20.00, amount_max=100.00)
    assert len(rows) == 2
    assert {r.description for r in rows} == {"Internet bill", "Paper and pens"}
