import sqlite3
from decimal import Decimal

import pytest

from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService


@pytest.fixture()
def vendor_open_purchase_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Item')").lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Vendor', 'V')"
    ).lastrowid
    empty_vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Empty Vendor', 'E')"
    ).lastrowid

    try:
        yield conn, {
            "uom_id": int(uom_id),
            "product_id": int(product_id),
            "vendor_id": int(vendor_id),
            "empty_vendor_id": int(empty_vendor_id),
        }
    finally:
        conn.close()


def _create_purchase(
    conn,
    ids,
    purchase_id: str,
    date: str,
    total: float,
    paid: float = 0.0,
    applied: float = 0.0,
) -> PurchasesRepo:
    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id=purchase_id,
            vendor_id=ids["vendor_id"],
            date=date,
            total_amount=total,
            order_discount=0.0,
            payment_status="partial" if paid or applied else "unpaid",
            paid_amount=paid,
            advance_payment_applied=applied,
            notes=None,
            created_by=None,
        ),
        [
            PurchaseItem(
                None,
                purchase_id,
                ids["product_id"],
                1.0,
                ids["uom_id"],
                total,
                total + 10.0,
                0.0,
            )
        ],
    )
    conn.execute(
        """
        UPDATE purchases
        SET paid_amount = ?, advance_payment_applied = ?
        WHERE purchase_id = ?
        """,
        (paid, applied, purchase_id),
    )
    return repo


def test_vendor_open_purchases_match_current_repo_order_and_due(
    vendor_open_purchase_db,
):
    conn, ids = vendor_open_purchase_db
    repo = _create_purchase(conn, ids, "PO-OLD", "2026-06-01", 100.0, paid=40.0)
    _create_purchase(conn, ids, "PO-NEW-B", "2026-06-03", 120.0, applied=20.0)
    _create_purchase(conn, ids, "PO-NEW-A", "2026-06-03", 90.0, paid=90.0)
    returned_repo = _create_purchase(conn, ids, "PO-RET", "2026-06-02", 80.0)
    item_id = int(returned_repo.list_items("PO-RET")[0]["item_id"])
    returned_repo.record_return(
        pid="PO-RET",
        date="2026-06-04",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 0.25}],
        notes=None,
    )

    current_rows = repo.get_open_purchases_for_vendor(ids["vendor_id"])
    service_rows = AccountingService(conn).get_vendor_open_purchases(ids["vendor_id"])

    assert [row["purchase_id"] for row in current_rows] == [
        row.purchase_id for row in service_rows
    ]
    assert [row["purchase_id"] for row in current_rows] == [
        "PO-NEW-B",
        "PO-RET",
        "PO-OLD",
    ]
    assert [float(row["balance"]) for row in current_rows] == pytest.approx(
        [float(row.outstanding) for row in service_rows]
    )
    assert [float(row["balance"]) for row in current_rows] == pytest.approx(
        [100.0, 60.0, 60.0]
    )
    assert AccountingService(conn).get_vendor_open_purchases(
        ids["empty_vendor_id"]
    ) == ()


def test_vendor_purchase_totals_match_current_repo_totals(vendor_open_purchase_db):
    conn, ids = vendor_open_purchase_db
    repo = _create_purchase(conn, ids, "PO-1", "2026-06-01", 100.0, paid=30.0)
    _create_purchase(conn, ids, "PO-2", "2026-06-02", 80.0, applied=25.0)
    _create_purchase(conn, ids, "PO-3", "2026-06-04", 50.0, paid=50.0)

    assert repo.list_purchases_by_vendor(
        ids["vendor_id"],
        "2026-06-01",
        "2026-06-02",
    ) == list(
        AccountingService(conn).list_vendor_purchases(
            ids["vendor_id"],
            "2026-06-01",
            "2026-06-02",
        )
    )
    current_totals = repo.get_purchase_totals_for_vendor(
        ids["vendor_id"],
        "2026-06-01",
        "2026-06-02",
    )
    service_totals = AccountingService(conn).get_vendor_purchase_totals(
        ids["vendor_id"],
        "2026-06-01",
        "2026-06-02",
    )

    assert service_totals.purchases_total == Decimal("180.0")
    assert current_totals == {
        "purchases_total": pytest.approx(float(service_totals.purchases_total)),
        "paid_total": pytest.approx(float(service_totals.paid_total)),
        "advance_applied_total": pytest.approx(
            float(service_totals.advance_applied_total)
        ),
    }
    assert AccountingService(conn).get_vendor_purchase_totals(
        ids["empty_vendor_id"]
    ).purchases_total == 0
