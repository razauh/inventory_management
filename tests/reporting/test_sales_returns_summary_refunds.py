from __future__ import annotations

import sqlite3

import pytest

from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.schema import SQL


@pytest.fixture()
def sales_returns_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES (?, ?)",
        ("Refund Customer", "refund@example.com"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO sales (
            sale_id, customer_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, notes, created_by
        ) VALUES ('SO-REFUND', ?, '2026-06-10', 100.0, 0.0, 'unpaid', 0.0, 0.0, NULL, NULL)
        """,
        (int(customer_id),),
    )

    conn.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, cleared_date, clearing_state
        ) VALUES ('SO-REFUND', '2026-06-10', -20.0, 'Cash', 'other', '2026-06-12', 'cleared')
        """
    )
    conn.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, cleared_date, clearing_state
        ) VALUES ('SO-REFUND', '2026-06-11', -15.0, 'Cash', 'other', NULL, 'pending')
        """
    )
    conn.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, cleared_date, clearing_state
        ) VALUES ('SO-REFUND', '2026-06-11', -5.0, 'Cash', 'other', '2026-06-12', 'bounced')
        """
    )

    try:
        yield conn
    finally:
        conn.close()


def test_returns_summary_splits_requested_and_cleared_refunds(sales_returns_db: sqlite3.Connection) -> None:
    rows = ReportingRepo(sales_returns_db).returns_summary("2026-06-10", "2026-06-12")
    metrics = {row["metric"]: row["value"] for row in rows}

    assert metrics["Requested Refunds"] == pytest.approx(-40.0)
    assert metrics["Cleared Refunds"] == pytest.approx(-20.0)
    assert metrics["Returned Qty (base)"] == pytest.approx(0.0)
    assert metrics["Return Value"] == pytest.approx(0.0)
    assert metrics["COGS Reversed"] == pytest.approx(0.0)
