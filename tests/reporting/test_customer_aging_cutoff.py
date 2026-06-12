from __future__ import annotations

import sqlite3

import pytest

from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.repositories.sales_repo import SaleHeader, SaleItem, SalesRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.customer_aging_reports import CustomerAgingReports
from inventory_management.modules.reporting.financial_reports import FinancialReports


@pytest.fixture()
def cutoff_db(tmp_path):
    db_path = tmp_path / "customer-aging-cutoff.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES ('"'"'Cutoff Customer'"'"', '"'"'test@example.com'"'"')"
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('"'"'Piece'"'"')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('"'"'Cutoff Item'"'"')").lastrowid
    conn.execute(
        "INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base) VALUES (?, ?, 1, 1)",
        (product_id, uom_id),
    )

    conn.execute(
        """
        INSERT INTO inventory_transactions (product_id, quantity, uom_id, transaction_type, date)
        VALUES (?, 100.0, ?, 'adjustment', '2026-06-01')
        """,
        (product_id, uom_id),
    )

    sales_repo = SalesRepo(conn)
    sales_repo.create_sale(
        SaleHeader(
            sale_id="SALE-1",
            customer_id=int(customer_id),
            date="2026-06-01",
            total_amount=100.0,
            order_discount=0.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=None,
        ),
        [SaleItem(None, "SALE-1", int(product_id), 10.0, int(uom_id), 10.0, 0.0)],
    )
    item_id = int(sales_repo.list_items("SALE-1")[0]["item_id"])
    conn.commit()

    try:
        yield conn, int(customer_id), int(product_id), int(uom_id), item_id
    finally:
        conn.close()


def _remaining(row: sqlite3.Row | dict) -> float:
    return float(row["total_amount"]) - float(row["paid_amount"]) - float(row["advance_payment_applied"])


def test_customer_aging_cutoff_ignores_later_payments_returns_and_credit(cutoff_db) -> None:
    conn, customer_id, product_id, uom_id, item_id = cutoff_db

    conn.execute(
        """
        INSERT INTO sale_payments (
            sale_id, date, amount, method, instrument_type, clearing_state, cleared_date
        ) VALUES ('SALE-1', '2026-06-11', 20.0, 'Cash', 'other', 'cleared', '2026-06-11')
        """
    )
    conn.execute(
        """
        INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id)
        VALUES (?, '2026-06-12', 50.0, 'deposit', NULL)
        """,
        (customer_id,),
    )
    conn.execute(
        """
        INSERT INTO customer_advances (customer_id, tx_date, amount, source_type, source_id)
        VALUES (?, '2026-06-12', -10.0, 'applied_to_sale', 'SALE-1')
        """,
        (customer_id,),
    )
    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 2.0, ?, 'sale_return', 'sales', 'SALE-1', ?, '2026-06-13')
        """,
        (product_id, uom_id, item_id),
    )

    reporting = ReportingRepo(conn)
    aging = CustomerAgingReports(conn)
    financial = FinancialReports(conn)

    before_batch = reporting.customer_headers_as_of_batch([customer_id], "2026-06-10")[0]
    after_batch = reporting.customer_headers_as_of_batch([customer_id], "2026-06-14")[0]

    assert _remaining(before_batch) == pytest.approx(100.0)
    assert _remaining(after_batch) == pytest.approx(50.0)

    before_single = reporting.customer_headers_as_of(customer_id, "2026-06-10")[0]
    after_single = reporting.customer_headers_as_of(customer_id, "2026-06-14")[0]
    assert _remaining(before_single) == pytest.approx(100.0)
    assert _remaining(after_single) == pytest.approx(50.0)

    assert aging.compute_aging_snapshot(
        "2026-06-10",
        include_credit_column=False,
        customer_id=customer_id,
    ) == [
        {
            "customer_id": customer_id,
            "name": "Cutoff Customer",
            "total_due": 100.0,
            "b_0_30": 100.0,
            "b_31_60": 0.0,
            "b_61_90": 0.0,
            "b_91_plus": 0.0,
            "available_credit": 0.0,
        }
    ]

    assert aging.list_open_invoices(customer_id, "2026-06-10") == [
        {
            "doc_no": "SALE-1",
            "date": "2026-06-01",
            "total": 100.0,
            "paid": 0.0,
            "advance_applied": 0.0,
            "remaining": 100.0,
            "days_outstanding": 9,
        }
    ]

    financial_snapshot = financial.ar_ap_snapshot_as_of("2026-06-10")
    assert financial_snapshot["AR_total_due"] == pytest.approx(100.0)
    assert financial_snapshot["AP_total_due"] == pytest.approx(0.0)
