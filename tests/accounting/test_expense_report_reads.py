import sqlite3
from decimal import Decimal
import pytest
from database.schema import SQL
from modules.accounting import AccountingService


@pytest.fixture()
def expense_reports_db():
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


def test_get_expense_report_category_totals_all(expense_reports_db):
    conn, cats = expense_reports_db
    service = AccountingService(conn)

    # All categories for the period 2026-06-01 to 2026-06-30
    totals = service.get_expense_report_category_totals("2026-06-01", "2026-06-30", None)
    assert len(totals) == 3  # Office Supplies, Utilities, Uncategorized (sorted by name COLLATE NOCASE)

    # Uncategorized, Office Supplies, Utilities (alphabetical)
    assert totals[0].category_name == "(Uncategorized)"
    assert totals[0].category_id == 0
    assert totals[0].total_amount == Decimal("15.75")

    assert totals[1].category_name == "Office Supplies"
    assert totals[1].category_id == cats["supplies"]
    assert totals[1].total_amount == Decimal("45.00")

    assert totals[2].category_name == "Utilities"
    assert totals[2].category_id == cats["utilities"]
    assert totals[2].total_amount == Decimal("200.50")


def test_get_expense_report_category_totals_filter_specific_category(expense_reports_db):
    conn, cats = expense_reports_db
    service = AccountingService(conn)

    # Filter to Utilities only
    totals = service.get_expense_report_category_totals("2026-06-01", "2026-06-30", cats["utilities"])
    assert len(totals) == 1
    assert totals[0].category_name == "Utilities"
    assert totals[0].total_amount == Decimal("200.50")

    # Filter to Uncategorized only
    totals = service.get_expense_report_category_totals("2026-06-01", "2026-06-30", 0)
    assert len(totals) == 1
    assert totals[0].category_name == "(Uncategorized)"
    assert totals[0].total_amount == Decimal("15.75")


def test_get_expense_report_lines_all(expense_reports_db):
    conn, cats = expense_reports_db
    service = AccountingService(conn)

    lines = service.get_expense_report_lines("2026-06-01", "2026-06-30", None)
    assert len(lines) == 4
    # Ordered by date DESC, expense_id DESC
    assert lines[0].description == "Coffee"
    assert lines[1].description == "Internet bill"
    assert lines[2].description == "Paper and pens"
    assert lines[3].description == "Electric bill"


def test_get_expense_report_lines_filter_category(expense_reports_db):
    conn, cats = expense_reports_db
    service = AccountingService(conn)

    # Filter to Utilities only
    lines = service.get_expense_report_lines("2026-06-01", "2026-06-30", cats["utilities"])
    assert len(lines) == 2
    assert {l.description for l in lines} == {"Electric bill", "Internet bill"}

    # Filter to Uncategorized only
    lines = service.get_expense_report_lines("2026-06-01", "2026-06-30", 0)
    assert len(lines) == 1
    assert lines[0].description == "Coffee"
