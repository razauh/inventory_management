import sqlite3
from decimal import Decimal

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
    SupplierRefundPayload,
)


@pytest.fixture()
def supplier_refund_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    company_id = conn.execute(
        "INSERT INTO company_info (company_name) VALUES ('Refund Co')"
    ).lastrowid
    user_id = conn.execute(
        """
        INSERT INTO users (username, password_hash, full_name)
        VALUES ('refund-user', 'hash', 'Refund User')
        """
    ).lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Refund Vendor', 'Test')"
    ).lastrowid
    company_account_id = conn.execute(
        "INSERT INTO company_bank_accounts (company_id, label) VALUES (?, 'Bank')",
        (company_id,),
    ).lastrowid
    vendor_account_id = conn.execute(
        """
        INSERT INTO vendor_bank_accounts (vendor_id, label, bank_name, account_no)
        VALUES (?, 'Vendor Bank', 'Test Bank', 'V-1')
        """,
        (vendor_id,),
    ).lastrowid
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Refund Product')"
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
            purchase_id="PO-SUPPLIER-REFUND",
            vendor_id=int(vendor_id),
            date="2026-06-01",
            total_amount=0.0,
            order_discount=0.0,
            payment_status="unpaid",
            paid_amount=0.0,
            advance_payment_applied=0.0,
            notes=None,
            created_by=int(user_id),
        ),
        [
            PurchaseItem(
                None,
                "PO-SUPPLIER-REFUND",
                int(product_id),
                10.0,
                int(uom_id),
                10.0,
                12.0,
                0.0,
            )
        ],
    )
    item_id = int(repo.list_items("PO-SUPPLIER-REFUND")[0]["item_id"])
    try:
        yield {
            "conn": conn,
            "vendor_id": int(vendor_id),
            "company_account_id": int(company_account_id),
            "vendor_account_id": int(vendor_account_id),
            "user_id": int(user_id),
            "item_id": item_id,
        }
    finally:
        conn.close()


def _pay(conn, amount):
    PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-SUPPLIER-REFUND",
        amount=amount,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        cleared_date="2026-06-02",
        clearing_state="cleared",
        ref_no=None,
        notes=None,
        date="2026-06-02",
        created_by=None,
    )


def _refund_payload(db, amount=Decimal("15.00")):
    return SupplierRefundPayload(
        purchase_id="PO-SUPPLIER-REFUND",
        vendor_id=db["vendor_id"],
        amount=amount,
        date="2026-06-03",
        method="Bank Transfer",
        bank_account_id=db["company_account_id"],
        vendor_bank_account_id=db["vendor_account_id"],
        instrument_type="online",
        instrument_no="REF-15",
        instrument_date="2026-06-03",
        deposited_date="2026-06-03",
        cleared_date="2026-06-03",
        ref_no="RETURN-15",
        notes="Vendor refund",
        created_by=db["user_id"],
    )


def _return_payload(db, qty, mode):
    settlement = {"mode": mode}
    if mode == "refund_now":
        settlement.update(
            {
                "method": "Cash",
                "cleared_date": "2026-06-04",
                "date": "2026-06-04",
            }
        )
    return PurchaseReturnPayload(
        purchase_id="PO-SUPPLIER-REFUND",
        date="2026-06-04",
        created_by=db["user_id"],
        lines=({"item_id": db["item_id"], "qty_return": qty},),
        notes="Returned goods",
        settlement=settlement,
    )


def test_record_supplier_refund_event_preserves_purchase_refund_row(
    supplier_refund_db,
):
    db = supplier_refund_db
    AccountingService(db["conn"]).record_purchase_return_event(_return_payload(db, 2.0, "credit_note"))

    result = AccountingService(db["conn"]).record_supplier_refund_event(
        _refund_payload(db)
    )
    row = AccountingService(db["conn"]).get_supplier_refunds_for_purchase(
        "PO-SUPPLIER-REFUND"
    )[0]

    assert result.refund_id == row.refund_id
    assert row.vendor_id == db["vendor_id"]
    assert float(row.amount) == pytest.approx(15.0)
    assert row.method == "Bank Transfer"
    assert row.bank_account_id == db["company_account_id"]
    assert row.vendor_bank_account_id == db["vendor_account_id"]
    assert row.instrument_type == "online"
    assert row.instrument_no == "REF-15"
    assert row.ref_no == "RETURN-15"
    assert row.notes == "Vendor refund"


def test_supplier_refund_preserves_prior_refund_and_credit_note_behavior(
    supplier_refund_db,
):
    db = supplier_refund_db
    service = AccountingService(db["conn"])
    _pay(db["conn"], 100.0)

    service.record_purchase_return_event(_return_payload(db, 2.0, "refund_now"))
    service.record_purchase_return_event(_return_payload(db, 3.0, "credit_note"))

    refunds = service.get_supplier_refunds_for_purchase("PO-SUPPLIER-REFUND")
    credit = db["conn"].execute(
        """
        SELECT amount
        FROM vendor_advances
        WHERE source_type = 'return_credit'
          AND source_id = 'PO-SUPPLIER-REFUND'
        """
    ).fetchone()

    assert [float(row.amount) for row in refunds] == pytest.approx([20.0])
    assert float(credit["amount"]) == pytest.approx(30.0)
    assert VendorAdvancesRepo(db["conn"]).get_balance(db["vendor_id"]) == pytest.approx(
        30.0
    )


def test_supplier_refund_rejects_amount_above_unsettled_return_value(
    supplier_refund_db,
):
    db = supplier_refund_db
    conn = db["conn"]
    service = AccountingService(conn)

    service.record_purchase_return_event(_return_payload(db, 4.0, "credit_note"))

    with pytest.raises(ValueError, match="exceeds the remaining refundable value"):
        service.record_supplier_refund_event(_refund_payload(db, Decimal("45.00")))


def test_supplier_refund_rejects_refund_without_purchase_return_value(
    supplier_refund_db,
):
    db = supplier_refund_db
    conn = db["conn"]
    service = AccountingService(conn)

    with pytest.raises(ValueError, match="exceeds the remaining refundable value"):
        service.record_supplier_refund_event(_refund_payload(db, Decimal("10.00")))


def test_supplier_refund_rejects_repeated_over_refund(
    supplier_refund_db,
):
    db = supplier_refund_db
    conn = db["conn"]
    service = AccountingService(conn)

    service.record_purchase_return_event(_return_payload(db, 4.0, "credit_note"))

    service.record_supplier_refund_event(_refund_payload(db, Decimal("25.00")))

    with pytest.raises(ValueError, match="exceeds the remaining refundable value"):
        service.record_supplier_refund_event(_refund_payload(db, Decimal("20.00")))

    service.record_supplier_refund_event(_refund_payload(db, Decimal("15.00")))



