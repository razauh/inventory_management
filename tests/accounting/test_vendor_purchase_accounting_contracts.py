from decimal import Decimal
from inspect import signature

import pytest

from modules.accounting import (
    AccountingNotImplementedError,
    AccountingService,
    PurchaseFinancials,
    PurchasePaymentStatus,
    PurchasePaymentRow,
    PurchasePaymentSummary,
    PurchaseReturnEffect,
    PurchaseReturnPayload,
    PurchaseReturnPreviewLine,
    PurchaseReturnPreviewPayload,
    PurchaseReturnResult,
    PurchaseReturnTotals,
    PurchaseReturnValue,
    PurchaseTotalInputLine,
    PurchaseTotals,
    SupplierRefundMetadata,
    VendorAdvancePayload,
    VendorAdvanceResult,
    VendorOpenPurchase,
    VendorCreditLedgerRow,
    VendorPaymentMetadata,
    VendorPaymentPayload,
    VendorPaymentEffect,
    VendorPaymentResult,
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
    ("get_purchase_payment_summary", ("purchase_id",)),
    ("get_purchase_payment_history", ("purchase_id",)),
    ("preview_purchase_return_effect", ("payload",)),
    ("get_purchase_return_values", ("purchase_id",)),
    ("get_purchase_return_totals", ("purchase_id",)),
    ("get_purchase_financials", ("purchase_id",)),
    ("record_purchase_return_event", ("payload",)),
    ("validate_vendor_payment_metadata", ("metadata",)),
    ("validate_supplier_refund_metadata", ("metadata",)),
    ("preview_vendor_payment_effect", ("payload",)),
    ("record_vendor_payment_event", ("payload",)),
    ("update_vendor_payment_state", ("payment_id", "clearing_state", "cleared_date", "notes")),
    ("record_vendor_advance_event", ("payload",)),
    ("get_vendor_credit_ledger", ("vendor_id",)),
    ("preview_vendor_advance_allocation", ("vendor_id", "amount")),
    ("record_vendor_advance_with_auto_apply", ("payload",)),
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
    return_line = PurchaseReturnPreviewLine(
        quantity=Decimal("2"),
        purchase_price=Decimal("10.00"),
        item_discount=Decimal("1.00"),
        return_qty=Decimal("1"),
    )
    assert PurchaseReturnPreviewPayload(
        lines=(return_line,),
        order_discount=Decimal("2.00"),
    )
    assert PurchaseReturnEffect(
        value_factor=Decimal("0.8"),
        total_qty=Decimal("1"),
        total_value=Decimal("7.2"),
        line_values=(Decimal("7.2"),),
    )
    assert PurchaseReturnValue(
        transaction_id=3,
        item_id=4,
        qty_returned=Decimal("1"),
        unit_buy_price=Decimal("10.00"),
        unit_discount=Decimal("1.00"),
        return_date="2026-06-21",
        valuation_status="resolved",
        return_value=Decimal("9.00"),
    )
    assert PurchaseReturnTotals(qty=Decimal("1"), value=Decimal("9.00"))
    assert PurchaseReturnPayload(
        purchase_id=1,
        date="2026-06-21",
        created_by=None,
        lines=({"item_id": 4, "qty_return": 1},),
        notes=None,
        settlement={"mode": "credit_note"},
    )
    assert PurchaseReturnResult(
        purchase_id=1,
        transaction_ids=(9,),
        return_value=Decimal("9.00"),
        settlement_amount=Decimal("9.00"),
    )
    assert PurchasePaymentStatus(
        purchase_id=1,
        status="partial",
        paid_amount=Decimal("5.00"),
        applied_credit=Decimal("1.00"),
        remaining_due=Decimal("3.00"),
    )
    payment_row = PurchasePaymentRow(
        payment_id=4,
        purchase_id=1,
        date="2026-06-21",
        amount=Decimal("5.00"),
        method="Cash",
        clearing_state="cleared",
    )
    assert payment_row
    assert PurchasePaymentSummary(
        purchase_id=1,
        latest_payment=payment_row,
        paid_amount=Decimal("5.00"),
        applied_credit=Decimal("1.00"),
        remaining_due=Decimal("3.00"),
        status="partial",
        overpayment_credited=Decimal("2.00"),
    ).to_detail_payload() == {
        "method": "Cash",
        "amount": 5.0,
        "status": "cleared",
        "overpayment": 2.0,
        "counterparty_label": "Vendor",
    }
    assert VendorPaymentMetadata(vendor_id=2, method="Cash")
    assert SupplierRefundMetadata(vendor_id=2, method="Cash")
    effect = VendorPaymentEffect(
        purchase_id=1,
        vendor_id=2,
        amount_due=Decimal("10.00"),
        payment_amount=Decimal("8.00"),
        overpayment_credit=Decimal("0.00"),
    )
    assert VendorPaymentPayload(
        purchase_id=1,
        amount=Decimal("8.00"),
        method="Cash",
        date="2026-06-21",
    )
    assert VendorPaymentResult(payment_id=3, credit_tx_id=None, effect=effect)
    assert VendorAdvancePayload(
        vendor_id=2,
        amount=Decimal("12.00"),
        date="2026-06-21",
    )
    assert VendorAdvanceResult(
        tx_id=4,
        vendor_id=2,
        amount=Decimal("12.00"),
        source_type="deposit",
    )
    assert VendorCreditLedgerRow(
        tx_id=4,
        vendor_id=2,
        tx_date="2026-06-21",
        amount=Decimal("12.00"),
        source_type="deposit",
        source_id=None,
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


def test_unmigrated_vendor_purchase_methods_raise_not_implemented():
    service = AccountingService()

    with pytest.raises(AccountingNotImplementedError):
        service.get_purchase_financials(1)
