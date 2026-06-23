import sqlite3
from decimal import Decimal
import pytest
from database.schema import SQL
from modules.accounting import AccountingService
from database.repositories.dashboard_repo import DashboardRepo


@pytest.fixture()
def dashboard_expense_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    # Insert test expenses
    conn.execute(
        "INSERT INTO expenses (description, amount, date) VALUES (?, ?, ?)",
        ("Electric bill", 120.50, "2026-06-10")
    )
    conn.execute(
        "INSERT INTO expenses (description, amount, date) VALUES (?, ?, ?)",
        ("Paper and pens", 45.00, "2026-06-15")
    )
    conn.execute(
        "INSERT INTO expenses (description, amount, date) VALUES (?, ?, ?)",
        ("Coffee", 15.75, "2026-06-25")
    )

    try:
        yield conn
    finally:
        conn.close()


def test_accounting_service_dashboard_expense_total(dashboard_expense_db):
    service = AccountingService(dashboard_expense_db)

    # Full period
    total = service.get_dashboard_expense_total("2026-06-01", "2026-06-30")
    assert total == Decimal("181.25")

    # Filtered period
    total = service.get_dashboard_expense_total("2026-06-01", "2026-06-12")
    assert total == Decimal("120.50")

    # Empty period
    total = service.get_dashboard_expense_total("2026-07-01", "2026-07-31")
    assert total == Decimal("0.00")


def test_dashboard_repo_expenses_total_delegation(dashboard_expense_db):
    repo = DashboardRepo(dashboard_expense_db)

    # Full period
    assert repo.expenses_total("2026-06-01", "2026-06-30") == 181.25

    # Filtered period
    assert repo.expenses_total("2026-06-01", "2026-06-12") == 120.50


def test_dashboard_repo_summary_metrics(dashboard_expense_db):
    repo = DashboardRepo(dashboard_expense_db)
    metrics = repo.summary_metrics("2026-06-01", "2026-06-30")
    assert metrics["total_expenses"] == 181.25

    metrics_filtered = repo.summary_metrics("2026-06-01", "2026-06-12")
    assert metrics_filtered["total_expenses"] == 120.50


def test_sales_dashboard_metrics(dashboard_expense_db):
    service = AccountingService(dashboard_expense_db)
    metrics = service.get_sales_dashboard_metrics("2026-06-01", "2026-06-30")
    assert metrics.total_expenses == Decimal("181.25")

    metrics_filtered = service.get_sales_dashboard_metrics("2026-06-01", "2026-06-12")
    assert metrics_filtered.total_expenses == Decimal("120.50")
