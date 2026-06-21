from decimal import Decimal
from inspect import signature

import pytest

from modules.accounting import (
    AccountingNotImplementedError,
    AccountingService,
    PurchaseFinancials,
    PurchasePaymentStatus,
    PurchaseTotalInputLine,
    PurchaseTotals,
    VendorOpenPurchase,
    VendorPurchaseTotals,
    VendorStatement,
    VendorStatementEntry,
)


VENDOR_PURCHASE_METHODS = [
    ("get_purchase_totals", ("purchase_id",)),
    ("get_purchase_outstanding", ("purchase_id",)),
    ("get_purchase_remaining_due_header", ("purchase_id",)),
    ("get_purchase_payment_status", ("purchase_id",)),
    ("recalculate_purchase_payment_status", ("purchase_id",)),
    ("get_purchase_financials", ("purchase_id",)),
    ("get_vendor_advance_balance", ("vendor_id",)),
    ("get_vendor_advance_balances", ("vendor_ids",)),
    ("get_vendor_open_purchases", ("vendor_id",)),
    ("get_vendor_purchase_totals", ("vendor_id", "date_from", "date_to")),
    ("list_vendor_purchases", ("vendor_id", "date_from", "date_to")),
    ("get_vendor_statement", ("vendor_id", "start_date", "end_date")),
    ("preview_purchase_total", ("items", "order_discount")),
]


def test_vendor_purchase_service_contract_methods_exist():
    assert PurchaseTotals(
        purchase_id=1,
        subtotal_before_order_discount=Decimal("12.00"),
        order_discount=Decimal("2.00"),
        returned_value=Decimal("1.00"),
        net_total=Decimal("9.00"),
        stored_total=Decimal("10.00"),
    )
    assert PurchaseTotalInputLine(
        quantity=Decimal("2"),
        purchase_price=Decimal("10.00"),
        item_discount=Decimal("1.00"),
    )
    assert PurchasePaymentStatus(
        purchase_id=1,
        status="partial",
        paid_amount=Decimal("5.00"),
        applied_credit=Decimal("1.00"),
        remaining_due=Decimal("3.00"),
    )
    assert PurchaseFinancials(
        purchase_id=1,
        net_total=Decimal("9.00"),
        paid_amount=Decimal("5.00"),
        applied_credit=Decimal("1.00"),
        returned_value=Decimal("1.00"),
        refunded_amount=Decimal("0.00"),
        outstanding=Decimal("3.00"),
    )
    assert VendorOpenPurchase(
        purchase_id=1,
        vendor_id=2,
        purchase_date="2026-06-21",
        reference="PO-1",
        net_total=Decimal("9.00"),
        outstanding=Decimal("3.00"),
    )
    assert VendorPurchaseTotals(
        vendor_id=2,
        purchases_total=Decimal("12.00"),
        paid_total=Decimal("5.00"),
        advance_applied_total=Decimal("1.00"),
    )
    assert VendorStatement(
        vendor_id=2,
        start_date=None,
        end_date=None,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("3.00"),
        entries=(
            VendorStatementEntry(
                entry_date="2026-06-21",
                description="Purchase",
                debit=Decimal("3.00"),
                credit=Decimal("0.00"),
                balance=Decimal("3.00"),
            ),
        ),
    )

    for method_name, expected_parameters in VENDOR_PURCHASE_METHODS:
        method = getattr(AccountingService, method_name)
        parameters = tuple(signature(method).parameters)
        assert parameters == ("self", *expected_parameters)


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("get_purchase_financials", (1,)),
    ],
)
def test_unmigrated_vendor_purchase_methods_raise_not_implemented(method_name, args):
    service = AccountingService()

    with pytest.raises(AccountingNotImplementedError):
        getattr(service, method_name)(*args)
