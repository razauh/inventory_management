from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest
from PySide6.QtCore import QDate

from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.financial_reports import FinancialReportsTab
from inventory_management.modules.reporting.payment_reports import PaymentReportsTab


def _open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_schema_db(tmp_path) -> tuple[str, sqlite3.Connection]:
    db_path = tmp_path / "reporting_snapshot.sqlite"
    conn = _open_db(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SQL)
    conn.commit()
    return str(db_path), conn


@contextmanager
def _transaction_probe(snapshot_cm, repo: ReportingRepo, calls: list[tuple[str, bool]]):
    with snapshot_cm():
        calls.append(("snapshot_open", repo.conn.in_transaction))
        yield
        calls.append(("snapshot_close", repo.conn.in_transaction))


@pytest.fixture()
def financial_snapshot_db(tmp_path):
    db_path, conn = _create_schema_db(tmp_path)

    customer_id = conn.execute(
        "INSERT INTO customers (name, contact_info) VALUES (?, ?)",
        ("Snapshot Customer", "customer@example.com"),
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name, category) VALUES (?, ?)",
        ("Snapshot Product", "Test"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (int(product_id), int(uom_id)),
    )

    try:
        yield {
            "db_path": db_path,
            "conn": conn,
            "customer_id": int(customer_id),
            "product_id": int(product_id),
            "uom_id": int(uom_id),
        }
    finally:
        conn.close()


@pytest.fixture()
def payment_snapshot_db(tmp_path):
    db_path, conn = _create_schema_db(tmp_path)

    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES (?, ?)",
        ("Snapshot Vendor", "vendor@example.com"),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO purchases (
            purchase_id, vendor_id, date, total_amount, order_discount,
            payment_status, paid_amount, advance_payment_applied, notes, created_by
        ) VALUES ('PO-SNAPSHOT-BASE', ?, '2026-06-12', 100.0, 0.0, 'paid', 100.0, 0.0, NULL, NULL)
        """,
        (int(vendor_id),),
    )
    conn.execute(
        """
        INSERT INTO purchase_payments (
            purchase_id, date, amount, method, cleared_date, clearing_state
        ) VALUES ('PO-SNAPSHOT-BASE', '2026-06-12', 100.0, 'Cash', '2026-06-12', 'cleared')
        """
    )

    try:
        yield {"db_path": db_path, "conn": conn}
    finally:
        conn.close()


def test_financial_reports_refresh_uses_one_snapshot(app, qtbot, financial_snapshot_db) -> None:
    conn = financial_snapshot_db["conn"]
    tab = FinancialReportsTab(conn)
    qtbot.addWidget(tab)

    day = QDate.fromString("2026-06-12", "yyyy-MM-dd")
    tab.dt_asof.setDate(day)
    tab.dt_stmt_from.setDate(day)
    tab.dt_stmt_to.setDate(day)
    tab.dt_cash_from.setDate(day)
    tab.dt_cash_to.setDate(day)

    calls: list[tuple[str, bool]] = []
    repo = tab.logic.repo
    original_snapshot = repo.read_snapshot
    repo.read_snapshot = lambda: _transaction_probe(original_snapshot, repo, calls)

    original_arap = repo.customer_headers_as_of_batch
    original_income = tab.logic.income_statement
    original_cash = tab.logic.cash_collections_disbursements

    def wrapped_arap(*args, **kwargs):
        calls.append(("ar_ap", repo.conn.in_transaction))
        return original_arap(*args, **kwargs)

    def wrapped_income(*args, **kwargs):
        calls.append(("income", repo.conn.in_transaction))
        return original_income(*args, **kwargs)

    def wrapped_cash(*args, **kwargs):
        calls.append(("cash", repo.conn.in_transaction))
        return original_cash(*args, **kwargs)

    repo.customer_headers_as_of_batch = wrapped_arap
    tab.logic.income_statement = wrapped_income
    tab.logic.cash_collections_disbursements = wrapped_cash

    try:
        tab.refresh()
    finally:
        repo.read_snapshot = original_snapshot

    assert calls[0] == ("snapshot_open", True)
    assert ("ar_ap", True) in calls
    assert ("income", True) in calls
    assert ("cash", True) in calls
    assert calls[-1] == ("snapshot_close", True)


def test_payment_reports_refresh_holds_one_snapshot(app, qtbot, payment_snapshot_db) -> None:
    conn = payment_snapshot_db["conn"]
    tab = PaymentReportsTab(conn)
    qtbot.addWidget(tab)

    day = QDate.fromString("2026-06-12", "yyyy-MM-dd")
    tab.dt_from.setDate(day)
    tab.dt_to.setDate(day)

    calls: list[tuple[str, bool]] = []
    repo = tab.repo
    original_snapshot = repo.read_snapshot
    repo.read_snapshot = lambda: _transaction_probe(original_snapshot, repo, calls)

    original_collect = repo.sale_collections_by_day
    original_disburse = repo.purchase_disbursements_by_day

    def wrapped_collect(*args, **kwargs):
        calls.append(("collect", repo.conn.in_transaction))
        return original_collect(*args, **kwargs)

    def wrapped_disburse(*args, **kwargs):
        calls.append(("disburse", repo.conn.in_transaction))
        return original_disburse(*args, **kwargs)

    repo.sale_collections_by_day = wrapped_collect
    repo.purchase_disbursements_by_day = wrapped_disburse

    try:
        tab.refresh()
    finally:
        repo.read_snapshot = original_snapshot

    assert calls[0] == ("snapshot_open", True)
    assert ("collect", True) in calls
    assert ("disburse", True) in calls
    assert calls[-1] == ("snapshot_close", True)
    assert tab._rows_disb == [
        {
            "date": "2026-06-12",
            "gross_outflow": 100.0,
            "refunds_received": 0.0,
            "net_outflow": 100.0,
        }
    ]
