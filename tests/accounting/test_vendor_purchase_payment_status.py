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
from inventory_management.database.repositories.vendor_advances_repo import (
    VendorAdvancesRepo,
)
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService


@pytest.fixture()
def purchase_payment_status_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Payment Status Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Payment Status Vendor', 'Test')"
    ).lastrowid

    purchases = PurchasesRepo(conn)
    purchases.create_purchase(
        PurchaseHeader(
            purchase_id="PO-PAY-STATUS",
            vendor_id=int(vendor_id),
            date="2026-06-21",
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
                "PO-PAY-STATUS",
                int(product_id),
                1.0,
                int(uom_id),
                100.0,
                120.0,
                0.0,
            )
        ],
    )

    try:
        yield conn, purchases, int(vendor_id)
    finally:
        conn.close()


def _stored_status(conn):
    return conn.execute(
        """
        SELECT payment_status, paid_amount, advance_payment_applied
        FROM purchases
        WHERE purchase_id = 'PO-PAY-STATUS'
        """
    ).fetchone()


def _assert_service_matches_stored(conn):
    stored = _stored_status(conn)
    service_status = AccountingService(conn).get_purchase_payment_status(
        "PO-PAY-STATUS"
    )

    assert service_status.status == stored["payment_status"]
    assert float(service_status.paid_amount) == pytest.approx(stored["paid_amount"])
    assert float(service_status.applied_credit) == pytest.approx(
        stored["advance_payment_applied"]
    )


def _pay(conn, amount: float) -> int:
    return PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-PAY-STATUS",
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-21",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-21",
        created_by=None,
    )


def test_service_status_matches_stored_status_after_payment_changes(
    purchase_payment_status_db,
):
    conn, _purchases, _vendor_id = purchase_payment_status_db

    _assert_service_matches_stored(conn)
    payment_id = _pay(conn, 40.0)
    _assert_service_matches_stored(conn)

    conn.execute(
        "UPDATE purchase_payments SET amount = 100 WHERE payment_id = ?",
        (payment_id,),
    )
    _assert_service_matches_stored(conn)

    conn.execute("DELETE FROM purchase_payments WHERE payment_id = ?", (payment_id,))
    _assert_service_matches_stored(conn)


def test_service_status_matches_stored_status_after_credit_changes(
    purchase_payment_status_db,
):
    conn, purchases, vendor_id = purchase_payment_status_db
    advances = VendorAdvancesRepo(conn)
    advances.grant_credit(
        vendor_id,
        100.0,
        date="2026-06-21",
        notes=None,
        created_by=None,
    )

    application_id = advances.apply_credit_to_purchase(
        vendor_id,
        "PO-PAY-STATUS",
        40.0,
        date="2026-06-21",
        notes=None,
        created_by=None,
    )
    _assert_service_matches_stored(conn)

    conn.execute("DELETE FROM vendor_advances WHERE tx_id = ?", (application_id,))
    _assert_service_matches_stored(conn)

    payment_id = _pay(conn, 40.0)
    item_id = int(purchases.list_items("PO-PAY-STATUS")[0]["item_id"])
    purchases.record_return(
        pid="PO-PAY-STATUS",
        date="2026-06-21",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 0.6}],
        notes=None,
    )
    _assert_service_matches_stored(conn)

    conn.execute("DELETE FROM purchase_payments WHERE payment_id = ?", (payment_id,))
    _assert_service_matches_stored(conn)
