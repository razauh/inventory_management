from decimal import Decimal
from inspect import signature

import pytest

from modules.accounting import (
    AccountingNotImplementedError,
    AccountingService,
    CustomerBalance,
    CustomerOpenSale,
    CustomerStatement,
    CustomerStatementEntry,
    QuotationFinancials,
    SaleFinancialSummary,
    SaleInvoiceFinancials,
    SaleOutstanding,
    SalePaymentRow,
    SalePaymentStatus,
    SaleTotals,
)

CUSTOMER_SALES_METHODS = [
    ("get_customer_balance", ("customer_id",)),
    ("get_sale_totals", ("sale_id",)),
    ("get_sale_financial_summary", ("sale_id",)),
    ("get_sale_outstanding", ("sale_id",)),
    ("get_sale_payment_status", ("sale_id",)),
    ("get_sale_payment_history", ("sale_id",)),
    ("get_customer_credit_balance", ("customer_id",)),
    ("get_customer_open_sales", ("customer_id",)),
    ("get_customer_statement", ("customer_id", "start_date", "end_date")),
    ("get_sale_invoice_financials", ("sale_id",)),
    ("get_quotation_financials", ("quotation_id",)),
]


def test_customer_sales_service_contract_methods_exist():
    assert SaleTotals(
        sale_id=1,
        subtotal_before_order_discount=Decimal("12.00"),
        order_discount=Decimal("2.00"),
        returned_value=Decimal("1.00"),
        net_total=Decimal("9.00"),
        stored_total=Decimal("10.00"),
    )
    assert SaleFinancialSummary(
        sale_id=1,
        net_total=Decimal("9.00"),
        paid_amount=Decimal("5.00"),
        applied_credit=Decimal("1.00"),
        returned_value=Decimal("1.00"),
        outstanding=Decimal("3.00"),
    )
    assert SaleOutstanding(sale_id=1, outstanding=Decimal("3.00"))
    assert SalePaymentStatus(
        sale_id=1,
        status="partial",
        paid_amount=Decimal("5.00"),
        applied_credit=Decimal("1.00"),
        remaining_due=Decimal("3.00"),
    )
    payment_row = SalePaymentRow(
        payment_id=4,
        sale_id=1,
        date="2026-06-21",
        amount=Decimal("5.00"),
        method="Cash",
        clearing_state="cleared",
    )
    assert payment_row
    assert CustomerBalance(customer_id=1, balance=Decimal("10.00"))
    assert CustomerOpenSale(
        sale_id=1,
        customer_id=2,
        sale_date="2026-06-21",
        reference="S-1",
        net_total=Decimal("9.00"),
        outstanding=Decimal("3.00"),
    )
    assert CustomerStatement(
        customer_id=2,
        start_date=None,
        end_date=None,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("3.00"),
        entries=(
            CustomerStatementEntry(
                entry_date="2026-06-21",
                description="Sale",
                debit=Decimal("3.00"),
                credit=Decimal("0.00"),
                balance=Decimal("3.00"),
            ),
        ),
    )
    assert SaleInvoiceFinancials(
        sale_id=1,
        context={"key": "value"},
    )
    assert QuotationFinancials(
        quotation_id=1,
        context={"key": "value"},
    )

    for method_name, expected_parameters in CUSTOMER_SALES_METHODS:
        method = getattr(AccountingService, method_name)
        parameters = tuple(signature(method).parameters)
        assert parameters == ("self", *expected_parameters)


def test_unmigrated_customer_sales_methods_raise_not_implemented():
    service = AccountingService()

    with pytest.raises(AccountingNotImplementedError):
        service.get_sale_totals(1)
    with pytest.raises(AccountingNotImplementedError):
        service.get_sale_financial_summary(1)
    with pytest.raises(AccountingNotImplementedError):
        service.get_sale_payment_status(1)
    with pytest.raises(AccountingNotImplementedError):
        service.get_sale_payment_history(1)
    with pytest.raises(AccountingNotImplementedError):
        service.get_customer_open_sales(1)
    with pytest.raises(AccountingNotImplementedError):
        service.get_customer_statement(1)
    with pytest.raises(AccountingNotImplementedError):
        service.get_sale_invoice_financials(1)
    with pytest.raises(AccountingNotImplementedError):
        service.get_quotation_financials(1)
