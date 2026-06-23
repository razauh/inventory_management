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
from inventory_management.database.schema import SQL
from inventory_management.modules.accounting import AccountingService


@pytest.fixture()
def purchase_invoice_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    uom_id = conn.execute("INSERT INTO uoms (unit_name) VALUES ('Piece')").lastrowid
    product_id = conn.execute(
        "INSERT INTO products (name) VALUES ('Invoice Product')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO product_uoms (product_id, uom_id, is_base, factor_to_base)
        VALUES (?, ?, 1, 1)
        """,
        (product_id, uom_id),
    )
    vendor_id = conn.execute(
        """
        INSERT INTO vendors (name, contact_info, address)
        VALUES ('Invoice Vendor', 'Contact', 'Address')
        """
    ).lastrowid
    PurchasesRepo(conn).create_purchase(
        PurchaseHeader(
            "PO-INVOICE",
            int(vendor_id),
            "2026-06-01",
            0.0,
            5.0,
            "unpaid",
            0.0,
            0.0,
            None,
            None,
        ),
        [
            PurchaseItem(
                None,
                "PO-INVOICE",
                int(product_id),
                3.0,
                int(uom_id),
                10.0,
                12.0,
                0.0,
            )
        ],
    )
    PurchasePaymentsRepo(conn).record_payment(
        purchase_id="PO-INVOICE",
        amount=10.0,
        method="Cash",
        bank_account_id=None,
        vendor_bank_account_id=None,
        instrument_type=None,
        instrument_no=None,
        instrument_date=None,
        deposited_date=None,
        date="2026-06-01",
        clearing_state="cleared",
        cleared_date="2026-06-01",
        ref_no=None,
        notes=None,
        created_by=None,
    )

    try:
        yield conn
    finally:
        conn.close()


def test_purchase_invoice_financials_preserve_controller_context(
    purchase_invoice_db,
):
    invoice = AccountingService(purchase_invoice_db).get_purchase_invoice_financials(
        "PO-INVOICE"
    )

    assert invoice.context["vendor"]["name"] == "Invoice Vendor"
    assert invoice.context["items"][0]["idx"] == 1
    assert invoice.context["items"][0]["line_total"] == pytest.approx(30.0)
    assert invoice.context["totals"] == {
        "subtotal_before_order_discount": 30.0,
        "line_discount_total": 0,
        "order_discount": 5.0,
        "total": 25.0,
    }
    assert invoice.context["paid_amount"] == pytest.approx(10.0)
    assert invoice.context["remaining"] == pytest.approx(15.0)
    assert invoice.context["payments"][0]["amount"] == pytest.approx(10.0)


def test_purchase_invoice_financials_preview_discount_matches_totals(
    purchase_invoice_db,
):
    invoice = AccountingService(purchase_invoice_db).get_purchase_invoice_financials(
        "PO-INVOICE"
    )

    assert invoice.preview_context["totals"] == {
        "subtotal_before_order_discount": 30.0,
        "line_discount_total": 0,
        "order_discount": 5.0,
        "total": 25.0,
    }
    assert invoice.preview_context["initial_payment"]["amount"] == pytest.approx(10.0)


def test_purchase_invoice_preview_discount_policy_is_explicit(
    purchase_invoice_db,
):
    invoice = AccountingService(purchase_invoice_db).get_purchase_invoice_financials(
        "PO-INVOICE"
    )
    # Under aligned policy, preview order discount must match actual order discount (5.0)
    assert invoice.preview_context["totals"]["order_discount"] == pytest.approx(5.0)


def test_purchase_invoice_preview_totals_match_documented_discount_rule(
    purchase_invoice_db,
):
    invoice = AccountingService(purchase_invoice_db).get_purchase_invoice_financials(
        "PO-INVOICE"
    )
    # Under aligned policy, preview total must match actual total (25.0)
    assert invoice.preview_context["totals"]["total"] == pytest.approx(25.0)

