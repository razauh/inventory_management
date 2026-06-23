import sqlite3
from decimal import Decimal
import pytest
from database.schema import SQL
from modules.accounting import AccountingService


@pytest.fixture()
def expense_pl_db():
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


def test_get_profit_loss_expense_summary(expense_pl_db):
    conn, cats = expense_pl_db
    service = AccountingService(conn)

    # P&L middle block totals for 2026-06-01 to 2026-06-30
    summary = service.get_profit_loss_expense_summary("2026-06-01", "2026-06-30")

    # Expect total sum to be 120.50 + 45.00 + 15.75 = 181.25
    assert summary.total_expenses == Decimal("181.25")

    # Order should be category_name COLLATE NOCASE
    # '(Uncategorized)', 'Marketing', 'Office Supplies', 'Utilities' (alphabetical)
    assert len(summary.expenses) == 4

    assert summary.expenses[0].category_name == "(Uncategorized)"
    assert summary.expenses[0].category_id == 0
    assert summary.expenses[0].total_amount == Decimal("15.75")

    assert summary.expenses[1].category_name == "Marketing"
    assert summary.expenses[1].category_id == cats["marketing"]
    assert summary.expenses[1].total_amount == Decimal("0.00")  # Included, empty

    assert summary.expenses[2].category_name == "Office Supplies"
    assert summary.expenses[2].category_id == cats["supplies"]
    assert summary.expenses[2].total_amount == Decimal("45.00")

    assert summary.expenses[3].category_name == "Utilities"
    assert summary.expenses[3].category_id == cats["utilities"]
    assert summary.expenses[3].total_amount == Decimal("120.50")
