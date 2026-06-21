import sqlite3

import pytest

from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo,
)
from inventory_management.database.repositories.vendors_repo import VendorsRepo
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService


@pytest.fixture()
def vendor_balance_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    vendor_a = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor A', 'A')"
    ).lastrowid
    vendor_b = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor B', 'B')"
    ).lastrowid

    try:
        yield conn, int(vendor_a), int(vendor_b)
    finally:
        conn.close()


def _add_advance(conn, vendor_id: int, amount: float, source_type: str) -> None:
    conn.execute(
        """
        INSERT INTO vendor_advances (vendor_id, tx_date, amount, source_type)
        VALUES (?, '2026-06-21', ?, ?)
        """,
        (vendor_id, amount, source_type),
    )


def test_vendor_advance_balance_matches_current_view(vendor_balance_db):
    conn, vendor_a, vendor_b = vendor_balance_db
    _add_advance(conn, vendor_a, 40.0, "deposit")
    service = AccountingService(conn)

    view_balance = conn.execute(
        "SELECT balance FROM v_vendor_advance_balance WHERE vendor_id = ?",
        (vendor_a,),
    ).fetchone()["balance"]

    assert float(service.get_vendor_advance_balance(vendor_a).balance) == pytest.approx(
        view_balance
    )
    assert VendorAdvancesRepo(conn).get_balance(vendor_a) == pytest.approx(view_balance)
    assert VendorsRepo(conn).vendor_balances([vendor_a, vendor_b]) == {
        vendor_a: pytest.approx(40.0),
        vendor_b: pytest.approx(0.0),
    }
    assert service.get_vendor_advance_balance(vendor_b).balance == 0


def test_vendor_advance_balance_preserves_signed_rows(vendor_balance_db):
    conn, vendor_a, _vendor_b = vendor_balance_db
    _add_advance(conn, vendor_a, 100.0, "deposit")
    _add_advance(conn, vendor_a, -35.0, "applied_to_purchase")
    _add_advance(conn, vendor_a, 15.0, "return_credit")

    balance = AccountingService(conn).get_vendor_advance_balance(vendor_a)

    assert float(balance.balance) == pytest.approx(80.0)
