from __future__ import annotations

import sqlite3

import pytest

from inventory_management.database.repositories.purchase_payments_repo import (
    PurchasePaymentsRepo,
)
from inventory_management.database.repositories.purchases_repo import (
    PurchaseHeader,
    PurchaseItem,
    PurchasesRepo,
)
from inventory_management.database.repositories.reporting_repo import ReportingRepo
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.reporting.financial_reports import FinancialReports


@pytest.fixture()
def ap_cutoff_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Cutoff Vendor', 'Test')"
    ).lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Cutoff Product')"
    ).lastrowid
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
            purchase_id="PO-CUTOFF",
            vendor_id=int(vendor_id),
            date="2026-06-01",
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
                "PO-CUTOFF",
                int(product_id),
                10.0,
                int(uom_id),
                10.0,
                12.0,
                0.0,
            )
        ],
    )
    item_id = int(repo.list_items("PO-CUTOFF")[0]["item_id"])

    try:
        yield conn, int(vendor_id), int(product_id), int(uom_id), item_id
    finally:
        conn.close()


def _remaining(row: sqlite3.Row | dict) -> float:
    return float(row["total_amount"]) - float(row["paid_amount"]) - float(row["advance_payment_applied"])


def test_vendor_aging_cutoff_ignores_later_payments_returns_and_credit(ap_cutoff_db) -> None:
    conn, vendor_id, product_id, uom_id, item_id = ap_cutoff_db

    PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-CUTOFF",
        amount=20.0,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-11",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-11",
        created_by=None,
    )

    conn.execute(
        """
        INSERT INTO inventory_transactions (
            product_id, quantity, uom_id, transaction_type,
            reference_table, reference_id, reference_item_id, date
        ) VALUES (?, 2.0, ?, 'purchase_return', 'purchases', 'PO-CUTOFF', ?, '2026-06-12')
        """,
        (product_id, uom_id, item_id),
    )

    credit_repo = VendorAdvancesRepo(conn)
    credit_repo.grant_credit(
        vendor_id,
        25.0,
        date="2026-06-13",
        notes="Later credit",
        created_by=None,
    )
    credit_repo.apply_credit_to_purchase(
        vendor_id,
        "PO-CUTOFF",
        15.0,
        date="2026-06-14",
        notes="Later credit application",
        created_by=None,
    )

    reporting = ReportingRepo(conn)
    financial = FinancialReports(conn)

    before_single = reporting.vendor_headers_as_of(vendor_id, "2026-06-10")[0]
    before_batch = reporting.vendor_headers_as_of_batch([vendor_id], "2026-06-10")[0]
    after_batch = reporting.vendor_headers_as_of_batch([vendor_id], "2026-06-15")[0]

    assert _remaining(before_single) == pytest.approx(100.0)
    assert _remaining(before_batch) == pytest.approx(100.0)
    assert _remaining(after_batch) == pytest.approx(45.0)

    before_snapshot = financial.ar_ap_snapshot_as_of("2026-06-10")
    after_snapshot = financial.ar_ap_snapshot_as_of("2026-06-15")

    assert before_snapshot["AP_total_due"] == pytest.approx(100.0)
    assert before_snapshot["AR_total_due"] == pytest.approx(0.0)
    assert after_snapshot["AP_total_due"] == pytest.approx(45.0)
