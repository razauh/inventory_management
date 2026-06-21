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
from inventory_management.modules.accounting import (
    AccountingService,
    PurchaseReturnPayload,
)


@pytest.fixture()
def purchase_return_event_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Return Event Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Return Event Vendor', 'Test')"
    ).lastrowid

    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id="PO-RETURN-EVENT",
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
                "PO-RETURN-EVENT",
                int(product_id),
                10.0,
                int(uom_id),
                10.0,
                12.0,
                0.0,
            )
        ],
    )
    item_id = int(repo.list_items("PO-RETURN-EVENT")[0]["item_id"])

    try:
        yield conn, int(vendor_id), item_id
    finally:
        conn.close()


def _pay(conn, amount):
    PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-RETURN-EVENT",
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-01",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-01",
        created_by=None,
    )


def test_record_purchase_return_event_preserves_inventory_and_snapshot_rows(
    purchase_return_event_db,
):
    conn, _vendor_id, item_id = purchase_return_event_db

    result = AccountingService(conn).record_purchase_return_event(
        PurchaseReturnPayload(
            purchase_id="PO-RETURN-EVENT",
            date="2026-06-02",
            created_by=None,
            lines=({"item_id": item_id, "qty_return": 2.0},),
            notes="Service return",
            settlement=None,
        )
    )

    tx = conn.execute(
        """
        SELECT *
        FROM inventory_transactions
        WHERE transaction_type = 'purchase_return'
          AND reference_id = 'PO-RETURN-EVENT'
        """
    ).fetchone()
    snapshot = conn.execute(
        "SELECT * FROM purchase_return_snapshots WHERE transaction_id = ?",
        (tx["transaction_id"],),
    ).fetchone()

    assert result.transaction_ids == (tx["transaction_id"],)
    assert float(result.return_value) == pytest.approx(20.0)
    assert float(tx["quantity"]) == pytest.approx(2.0)
    assert tx["reference_item_id"] == item_id
    assert float(snapshot["returned_quantity"]) == pytest.approx(2.0)
    assert float(snapshot["return_value"]) == pytest.approx(20.0)


def test_record_purchase_return_event_preserves_excess_settlement_behavior(
    purchase_return_event_db,
):
    conn, vendor_id, item_id = purchase_return_event_db
    _pay(conn, 100.0)

    result = AccountingService(conn).record_purchase_return_event(
        PurchaseReturnPayload(
            purchase_id="PO-RETURN-EVENT",
            date="2026-06-02",
            created_by=None,
            lines=({"item_id": item_id, "qty_return": 4.0},),
            notes="Service credit",
            settlement={"mode": "credit_note"},
        )
    )
    credit = conn.execute(
        """
        SELECT amount
        FROM vendor_advances
        WHERE source_type = 'return_credit'
          AND source_id = 'PO-RETURN-EVENT'
        """
    ).fetchone()

    assert float(result.return_value) == pytest.approx(40.0)
    assert float(result.settlement_amount) == pytest.approx(40.0)
    assert float(credit["amount"]) == pytest.approx(40.0)
    assert VendorAdvancesRepo(conn).get_balance(vendor_id) == pytest.approx(40.0)
