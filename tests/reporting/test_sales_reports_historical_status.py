from __future__ import annotations

import sqlite3

import pytest

from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import SQL


@pytest.fixture()
def historical_status_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES (?, ?)",
        ("Status Customer", "status@example.com"),
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Status Product')").lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (int(product_id), int(uom_id)),
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type, reference_table, reference_id, date
        ) VALUES (?, 1.0, ?, 'adjustment', NULL, NULL, '2026-06-10')
        """,
        (int(product_id), int(uom_id)),
    )

    repo = SalesRepo(conn)
    repo.create_sale(
        SaleHeader(
            sale_id="SO-HIST",
            customer_id=int(customer_id),
            date="2026-06-10",
            total_amount=100.0,
            order_discount=0.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=None,
        ),
        [SaleItem(None, "SO-HIST", int(product_id), 1.0, int(uom_id), 100.0, 0.0)],
    )

    try:
        yield conn
    finally:
        conn.close()


def test_sales_reports_use_status_as_of_cutoff(historical_status_db: sqlite3.Connection) -> None:
    repo = ReportingRepo(historical_status_db)

    unpaid_before = repo.sales_by_period(
        "2026-06-01",
        "2026-06-30",
        "monthly",
        ["unpaid"],
        None,
        None,
        None,
    )
    paid_before = repo.sales_by_period(
        "2026-06-01",
        "2026-06-30",
        "monthly",
        ["paid"],
        None,
        None,
        None,
    )
    margin_before = repo.margin_by_period(
        "2026-06-01",
        "2026-06-30",
        "monthly",
        ["unpaid"],
        None,
        None,
        None,
    )

    assert len(unpaid_before) == 1
    assert float(unpaid_before[0]["revenue"]) == pytest.approx(100.0)
    assert paid_before == []
    assert len(margin_before) == 1

    historical_status_db.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, cleared_date, clearing_state
        ) VALUES ('SO-HIST', '2026-07-01', 100.0, 'Cash', 'other', '2026-07-01', 'cleared')
        """
    )

    unpaid_after = repo.sales_by_period(
        "2026-06-01",
        "2026-06-30",
        "monthly",
        ["unpaid"],
        None,
        None,
        None,
    )
    paid_after = repo.sales_by_period(
        "2026-06-01",
        "2026-06-30",
        "monthly",
        ["paid"],
        None,
        None,
        None,
    )
    margin_after = repo.margin_by_period(
        "2026-06-01",
        "2026-06-30",
        "monthly",
        ["unpaid"],
        None,
        None,
        None,
    )
    drilldown_after = repo.drilldown_sales(
        "2026-06-01",
        "2026-06-30",
        ["unpaid"],
        None,
        None,
        None,
    )

    assert len(unpaid_after) == 1
    assert float(unpaid_after[0]["revenue"]) == pytest.approx(100.0)
    assert paid_after == []
    assert len(margin_after) == 1
    assert len(drilldown_after) == 1
    assert drilldown_after[0]["payment_status"] == "unpaid"
