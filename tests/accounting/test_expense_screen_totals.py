import sqlite3
from decimal import Decimal
import pytest
from database.schema import SQL
from modules.accounting import AccountingService


@pytest.fixture()
def expense_totals_db():
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
    cat_id3 = conn.execute(
        "INSERT INTO expense_categories (name) VALUES ('Marketing')"
    ).lastrowid  # Empty category

    # Insert test expenses
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
            "marketing": int(cat_id3),
        }
    finally:
        conn.close()


def test_get_expense_screen_category_totals_all(expense_totals_db):
    conn, cats = expense_totals_db
    service = AccountingService(conn)

    totals = service.get_expense_screen_category_totals()
    # Expecting 4 items: '(Uncategorized)', 'Marketing', 'Office Supplies', 'Utilities' (ordered alphabetically)
    assert len(totals) == 4

    assert totals[0].category_name == "(Uncategorized)"
    assert totals[0].category_id == 0
    assert totals[0].total_amount == Decimal("15.75")

    assert totals[1].category_name == "Marketing"
    assert totals[1].category_id == cats["marketing"]
    assert totals[1].total_amount == Decimal("0.00")

    assert totals[2].category_name == "Office Supplies"
    assert totals[2].category_id == cats["supplies"]
    assert totals[2].total_amount == Decimal("45.00")

    assert totals[3].category_name == "Utilities"
    assert totals[3].category_id == cats["utilities"]
    assert totals[3].total_amount == Decimal("200.50")


def test_get_expense_screen_category_totals_filter_query(expense_totals_db):
    conn, cats = expense_totals_db
    service = AccountingService(conn)

    # Filter by query "bill" -> should only count "Electric bill" and "Internet bill"
    totals = service.get_expense_screen_category_totals(query="bill")
    assert len(totals) == 4

    # Marketing, Office Supplies, and Uncategorized should be 0.00
    # Utilities should be 200.50
    t_dict = {t.category_name: t.total_amount for t in totals}
    assert t_dict["(Uncategorized)"] == Decimal("0.00")
    assert t_dict["Marketing"] == Decimal("0.00")
    assert t_dict["Office Supplies"] == Decimal("0.00")
    assert t_dict["Utilities"] == Decimal("200.50")


def test_get_expense_screen_category_totals_filter_specific_category(expense_totals_db):
    conn, cats = expense_totals_db
    service = AccountingService(conn)

    # Filter to only category_id = Utilities
    totals = service.get_expense_screen_category_totals(category_id=cats["utilities"])
    # If category_id is specific, the list should not contain uncategorized unless it's category_id = 0
    # Let's check how the original repo behavior builds this:
    # If category_id is set to a named category, Part 2 (Uncategorized) is omitted from SQL union parts because:
    # "if category_id is None or category_id == 0: ... append UNION ALL for Uncategorized"
    # So for category_id = Utilities, it should only return named categories (and only Utilities will have total if filters match,
    # wait - actually, the LEFT JOIN in Part 1 is 'ON e.category_id = c.category_id AND e.category_id = ?').
    # Let's verify the actual length and contents of totals.
    assert len(totals) == 3  # All named categories, no uncategorized
    t_dict = {t.category_name: t.total_amount for t in totals}
    assert "Marketing" in t_dict
    assert "Office Supplies" in t_dict
    assert "Utilities" in t_dict
    assert t_dict["Utilities"] == Decimal("200.50")
    assert t_dict["Marketing"] == Decimal("0.00")
    assert t_dict["Office Supplies"] == Decimal("0.00")


def test_get_expense_screen_category_totals_filter_uncategorized(expense_totals_db):
    conn, cats = expense_totals_db
    service = AccountingService(conn)

    # Filter to category_id = 0 (Uncategorized)
    totals = service.get_expense_screen_category_totals(category_id=0)
    # Includes named categories (which will have 0.0 because of the filter in LEFT JOIN on clause) AND uncategorized
    assert len(totals) == 4
    t_dict = {t.category_name: t.total_amount for t in totals}
    assert t_dict["(Uncategorized)"] == Decimal("15.75")
    assert t_dict["Utilities"] == Decimal("0.00")
    assert t_dict["Office Supplies"] == Decimal("0.00")
