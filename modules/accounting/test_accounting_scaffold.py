import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from decimal import Decimal

import pytest

from modules.accounting import (
    AccountingEvent,
    AccountingNotImplementedError,
    AccountingService,
    CustomerAgingReport,
    CustomerBalance,
    CustomerOpenSale,
    CustomerReceivableSummary,
    CustomerStatement,
    CustomerStatementEntry,
    JournalPreview,
    PartyLedgerSummary,
    PurchaseOutstanding,
    PurchaseReturnPayload,
    QuotationFinancials,
    SaleFinancialSummary,
    SaleInvoiceFinancials,
    SaleOutstanding,
    SalePaymentRow,
    SalePaymentStatus,
    SalesDashboardMetrics,
    SaleTotalInputLine,
    SaleTotals,
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
        ("get_vendor_advance_balance", (1,)),
        ("get_customer_credit_balance", (1,)),
        ("get_bank_balance", (1,)),
        ("get_inventory_value", ()),
        ("record_purchase_event", ()),
        ("record_sale_event", ()),
        ("record_vendor_payment_event", ()),
        ("record_customer_payment_event", (None,)),
        (
            "record_purchase_return_event",
            (
                PurchaseReturnPayload(
                    purchase_id=1,
                    date="2026-06-21",
                    created_by=None,
                    lines=(),
                ),
            ),
        ),
        ("record_sale_return_event", ()),
        ("record_expense_event", ()),
        ("record_stock_adjustment_event", ()),
        ("get_customer_open_sales", (1,)),
        ("get_purchase_totals", (1,)),
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
    assert SaleTotalInputLine(quantity=Decimal("2"), unit_price=Decimal("10"), item_discount=Decimal("1"))
    assert SaleTotals(sale_id=1, subtotal_before_order_discount=Decimal("10"), order_discount=Decimal("0"), returned_value=Decimal("0"), net_total=Decimal("10"))
    assert SaleFinancialSummary(sale_id=1, gross_total_amount=Decimal("10"), net_total=Decimal("10"), paid_amount=Decimal("0"), applied_credit=Decimal("0"), returned_value=Decimal("0"), outstanding=Decimal("10"))
    assert SalePaymentStatus(sale_id=1, status="paid", paid_amount=Decimal("10"), applied_credit=Decimal("0"), remaining_due=Decimal("0"))
    assert SalePaymentRow(payment_id=1, sale_id=1, date="2026-06-21", amount=Decimal("10"), method="Cash")
    assert CustomerOpenSale(sale_id=1, customer_id=1, sale_date=None, reference=None, net_total=Decimal("10"), outstanding=Decimal("10"))
    assert CustomerStatementEntry(entry_date="2026-06-21", description="Sale", debit=Decimal("10"), credit=Decimal("0"), balance=Decimal("10"))
    assert CustomerAgingReport(as_of="2026-06-21", rows=())
    assert CustomerReceivableSummary(customer_id=1, credit_balance=Decimal("10"), sales_count=2, open_due_sum=Decimal("50"))
    assert SalesDashboardMetrics(as_of="2026-06-21", total_sales=Decimal("100"), total_cogs=Decimal("60"), total_expenses=Decimal("20"), receipts_cleared=Decimal("40"), vendor_payments_cleared=Decimal("0"), open_receivables=Decimal("60"), open_payables=Decimal("0"))
    assert CustomerStatement(customer_id=1, start_date=None, end_date=None, opening_balance=Decimal("0"), closing_balance=Decimal("10"))
    assert SaleInvoiceFinancials(sale_id=1, context={})
    assert QuotationFinancials(quotation_id=1, context={})
    assert PartyLedgerSummary(party_type="vendor", party_id=1, balance=Decimal("10.00"))
    assert AccountingEvent(event_type="purchase", source_type="purchase", source_id=1)
    assert JournalPreview(source_type="purchase", source_id=1)
