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
from inventory_management.modules.accounting import AccountingService


@pytest.fixture()
def purchase_outstanding_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)

    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    vendor_id = conn.execute(
        "INSERT INTO vendors (name, contact_info) VALUES ('Outstanding Vendor', 'Test')"
    ).lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Outstanding Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )

    try:
        yield conn, {
            "uom_id": int(uom_id),
            "vendor_id": int(vendor_id),
            "product_id": int(product_id),
        }
    finally:
        conn.close()


def _create_purchase(conn, ids, purchase_id: str) -> PurchasesRepo:
    repo = PurchasesRepo(conn)
    repo.create_purchase(
        PurchaseHeader(
            purchase_id=purchase_id,
            vendor_id=ids["vendor_id"],
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
                purchase_id,
                ids["product_id"],
                1.0,
                ids["uom_id"],
                100.0,
                120.0,
                0.0,
            )
        ],
    )
    return repo


def _pay(conn, purchase_id: str, amount: float) -> None:
    PurchasePaymentsRepo(conn).record_payment(
        purchase_id=purchase_id,
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


def test_purchase_outstanding_matches_repo_remaining_due(purchase_outstanding_db):
    conn, ids = purchase_outstanding_db
    repo = _create_purchase(conn, ids, "PO-DUE")
    service = AccountingService(conn)

    assert service.get_purchase_remaining_due_header("PO-DUE").outstanding == 100
    assert repo.get_remaining_due_header("PO-DUE") == pytest.approx(100.0)

    _pay(conn, "PO-DUE", 40.0)
    assert float(service.get_purchase_outstanding("PO-DUE").outstanding) == (
        pytest.approx(repo.get_purchase_remaining_due("PO-DUE")["remaining_due"])
    )
    assert repo.get_remaining_due_header("PO-DUE") == pytest.approx(60.0)

    _pay(conn, "PO-DUE", 60.0)
    assert repo.get_remaining_due_header("PO-DUE") == pytest.approx(0.0)

    conn.execute("UPDATE purchases SET paid_amount = 120 WHERE purchase_id = 'PO-DUE'")
    assert float(service.get_purchase_outstanding("PO-DUE").outstanding) == -20.0
    assert float(service.get_purchase_remaining_due_header("PO-DUE").outstanding) == 0.0
    assert repo.get_purchase_remaining_due("PO-DUE")["remaining_due"] == -20.0
    assert repo.get_remaining_due_header("PO-DUE") == pytest.approx(0.0)


def test_purchase_outstanding_preserves_returns_payments_and_applied_credit(
    purchase_outstanding_db,
):
    conn, ids = purchase_outstanding_db
    repo = _create_purchase(conn, ids, "PO-DUE-RETURN")
    item_id = int(repo.list_items("PO-DUE-RETURN")[0]["item_id"])
    repo.record_return(
        pid="PO-DUE-RETURN",
        date="2026-06-21",
        created_by=None,
        lines=[{"item_id": item_id, "qty_return": 0.25}],
        notes=None,
    )
    _pay(conn, "PO-DUE-RETURN", 25.0)

    advances = VendorAdvancesRepo(conn)
    advances.grant_credit(
        ids["vendor_id"],
        50.0,
        date="2026-06-21",
        notes=None,
        created_by=None,
    )
    advances.apply_credit_to_purchase(
        ids["vendor_id"],
        "PO-DUE-RETURN",
        10.0,
        date="2026-06-21",
        notes=None,
        created_by=None,
    )

    expected = repo.get_purchase_remaining_due("PO-DUE-RETURN")
    outstanding = AccountingService(conn).get_purchase_outstanding("PO-DUE-RETURN")

    assert float(outstanding.outstanding) == pytest.approx(expected["remaining_due"])
    assert expected["remaining_due"] == pytest.approx(40.0)


def test_purchase_outstanding_api_conventions_match_documented_policy(purchase_outstanding_db):
    conn, ids = purchase_outstanding_db
    _create_purchase(conn, ids, "PO-POLICY")
    service = AccountingService(conn)

    # Unpaid purchase of 100
    financials = service.get_purchase_financials("PO-POLICY")
    outstanding = service.get_purchase_outstanding("PO-POLICY")
    remaining_due_header = service.get_purchase_remaining_due_header("PO-POLICY")

    assert financials.outstanding == Decimal("100.0")
    assert financials.clamped_outstanding == Decimal("100.0")
    assert outstanding.outstanding == Decimal("100.0")
    assert remaining_due_header.outstanding == Decimal("100.0")

    # Partially paid: 40 paid
    _pay(conn, "PO-POLICY", 40.0)
    financials = service.get_purchase_financials("PO-POLICY")
    outstanding = service.get_purchase_outstanding("PO-POLICY")
    remaining_due_header = service.get_purchase_remaining_due_header("PO-POLICY")

    assert financials.outstanding == Decimal("60.0")
    assert financials.clamped_outstanding == Decimal("60.0")
    assert outstanding.outstanding == Decimal("60.0")
    assert remaining_due_header.outstanding == Decimal("60.0")


def test_purchase_outstanding_overpayment_values_are_exposed_consistently(purchase_outstanding_db):
    conn, ids = purchase_outstanding_db
    _create_purchase(conn, ids, "PO-OVER")
    service = AccountingService(conn)

    # Force paid_amount = 120 (overpayment of 20)
    conn.execute("UPDATE purchases SET paid_amount = 120 WHERE purchase_id = 'PO-OVER'")

    # All 3 APIs must evaluate consistently based on p.paid_amount
    financials = service.get_purchase_financials("PO-OVER")
    outstanding_signed = service.get_purchase_outstanding("PO-OVER", clamp=False)
    outstanding_clamped = service.get_purchase_outstanding("PO-OVER", clamp=True)
    remaining_due_header = service.get_purchase_remaining_due_header("PO-OVER")

    # Assert signed conventions
    assert financials.outstanding == Decimal("-20.0")
    assert outstanding_signed.outstanding == Decimal("-20.0")

    # Assert clamped conventions
    assert financials.clamped_outstanding == Decimal("0.0")
    assert outstanding_clamped.outstanding == Decimal("0.0")
    assert remaining_due_header.outstanding == Decimal("0.0")
