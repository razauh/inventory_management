from __future__ import annotations

import sqlite3

import pytest
from PySide6.QtCore import QDate

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.purchase_reports import PurchaseReportsTab


@pytest.fixture()
def purchase_reports_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Report Vendor', 'Test')"
    ).lastrowid
    product_id = conn.execute("INSERT INTO products (name) VALUES ('Report Product')").lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id="PO-REPORT-NET",
            vendor_id=int(vendor_id),
            date="2026-06-10",
            total_amount=0.0,
            order_discount=0.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=None,
        ),
        [
            PurchaseItem(
                None,
                "PO-REPORT-NET",
                int(product_id),
                10.0,
                int(uom_id),
                10.0,
                15.0,
                0.0,
            )
        ],
    )
    item_id = int(repo.list_items("PO-REPORT-NET")[0]["item_id"])
    PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-REPORT-NET",
        amount=20.0,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-10",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-10",
        created_by=None,
    )
    repo.record_return(
        pid="PO-REPORT-NET",
        date="2026-06-10",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 4.0}],
        notes="Returned stock",
    )

    try:
        yield conn
    finally:
        conn.close()


def _rows(tab: PurchaseReportsTab, key: str) -> list[dict]:
    tv = tab._tables[key]
    model = tv.model()
    return [model._rows[i] for i in range(model.rowCount())]


def test_purchase_reports_use_net_total_after_returns(app, purchase_reports_db) -> None:
    tab = PurchaseReportsTab(purchase_reports_db)
    cutoff = QDate(2026, 6, 10)
    tab.dt_from.setDate(cutoff)
    tab.dt_to.setDate(cutoff)
    tab.refresh()

    assert _rows(tab, "purch_by_period")[0]["spend"] == pytest.approx(60.0)
    assert _rows(tab, "purch_by_vendor")[0]["spend"] == pytest.approx(60.0)
    assert _rows(tab, "top_vendors")[0]["spend"] == pytest.approx(60.0)
    assert _rows(tab, "status_breakdown")[0]["spend"] == pytest.approx(60.0)

    open_row = _rows(tab, "open_purchases")[0]
    drill_row = _rows(tab, "drilldown")[0]
    assert open_row["total_amount"] == pytest.approx(60.0)
    assert open_row["remaining"] == pytest.approx(40.0)
    assert drill_row["total_amount"] == pytest.approx(60.0)
    assert drill_row["remaining"] == pytest.approx(40.0)
