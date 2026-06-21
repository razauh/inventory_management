from decimal import Decimal

import pytest

from modules.accounting import (
    AccountingEvent,
    AccountingNotImplementedError,
    AccountingService,
    CustomerBalance,
    JournalPreview,
    PartyLedgerSummary,
    PurchaseOutstanding,
    SaleOutstanding,
    VendorBalance,
)


def test_accounting_package_imports_and_service_instantiates():
    assert AccountingService()


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("get_vendor_balance", (1,)),
        ("get_customer_balance", (1,)),
        ("get_purchase_outstanding", (1,)),
        ("get_sale_outstanding", (1,)),
        ("get_vendor_advance_balance", (1,)),
        ("get_customer_credit_balance", (1,)),
        ("get_bank_balance", (1,)),
        ("get_inventory_value", ()),
        ("record_purchase_event", ()),
        ("record_sale_event", ()),
        ("record_vendor_payment_event", ()),
        ("record_customer_receipt_event", ()),
        ("record_purchase_return_event", ()),
        ("record_sale_return_event", ()),
        ("record_expense_event", ()),
        ("record_stock_adjustment_event", ()),
    ],
)
def test_accounting_service_placeholders_raise_accounting_error(method_name, args):
    service = AccountingService()

    with pytest.raises(AccountingNotImplementedError):
        getattr(service, method_name)(*args)


def test_accounting_dtos_construct():
    assert VendorBalance(vendor_id=1, balance=Decimal("10.00"))
    assert CustomerBalance(customer_id=1, balance=Decimal("10.00"))
    assert PurchaseOutstanding(purchase_id=1, outstanding=Decimal("10.00"))
    assert SaleOutstanding(sale_id=1, outstanding=Decimal("10.00"))
    assert PartyLedgerSummary(party_type="vendor", party_id=1, balance=Decimal("10.00"))
    assert AccountingEvent(event_type="purchase", source_type="purchase", source_id=1)
    assert JournalPreview(source_type="purchase", source_id=1)
