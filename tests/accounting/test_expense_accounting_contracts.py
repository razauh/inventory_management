from decimal import Decimal
from inspect import signature

import pytest

from modules.accounting import (
    AccountingNotImplementedError,
    AccountingService,
    ExpenseFinancialSummary,
    ExpenseCategoryTotal,
    ExpenseReportLine,
    ExpenseProfitLossSummary,
)

EXPENSE_METHODS = [
    ("get_expense_financial_summary", ("expense_id",)),
    ("list_expense_rows", None),  # uses *args, **kwargs
    ("get_expense_screen_category_totals", None),  # uses *args, **kwargs
    ("get_expense_report_category_totals", None),  # uses *args, **kwargs
    ("get_expense_report_lines", None),  # uses *args, **kwargs
    ("get_dashboard_expense_total", ("date_from", "date_to")),
    ("get_profit_loss_expense_summary", ("date_from", "date_to")),
    ("validate_expense_input", None),  # uses *args, **kwargs
    ("record_expense_create_event", None),  # uses *args, **kwargs
    ("record_expense_update_event", None),  # uses *args, **kwargs
    ("record_expense_delete_event", ("expense_id",)),
]


def test_expense_service_contract_methods_exist():
    # Instantiate DTOs to check their contracts
    summary = ExpenseFinancialSummary(
        expense_id=1,
        description="Office supplies",
        amount=Decimal("150.00"),
        date="2026-06-23",
        category_id=2,
        category_name="Supplies",
    )
    assert summary

    cat_total = ExpenseCategoryTotal(
        category_id=2,
        category_name="Supplies",
        total_amount=Decimal("350.00"),
    )
    assert cat_total

    report_line = ExpenseReportLine(
        expense_id=1,
        date="2026-06-23",
        category_name="Supplies",
        description="Office supplies",
        amount=Decimal("150.00"),
    )
    assert report_line

    pl_summary = ExpenseProfitLossSummary(
        expenses=(cat_total,),
        total_expenses=Decimal("350.00"),
    )
    assert pl_summary

    for method_name, expected_parameters in EXPENSE_METHODS:
        method = getattr(AccountingService, method_name)
        parameters = tuple(signature(method).parameters)
        if expected_parameters is not None:
            assert parameters == ("self", *expected_parameters)
        else:
            assert "self" in parameters


def test_unmigrated_expense_methods_raise_not_implemented():
    service = AccountingService()

    with pytest.raises(AccountingNotImplementedError):
        service.get_expense_financial_summary(1)
    with pytest.raises(AccountingNotImplementedError):
        service.list_expense_rows()
    with pytest.raises(AccountingNotImplementedError):
        service.get_expense_screen_category_totals()
    with pytest.raises(AccountingNotImplementedError):
        service.get_expense_report_category_totals("2026-06-01", "2026-06-30", None)
    with pytest.raises(AccountingNotImplementedError):
        service.get_expense_report_lines("2026-06-01", "2026-06-30", None)
    with pytest.raises(AccountingNotImplementedError):
        service.get_dashboard_expense_total("2026-06-01", "2026-06-30")
    with pytest.raises(AccountingNotImplementedError):
        service.get_profit_loss_expense_summary("2026-06-01", "2026-06-30")
    with pytest.raises(AccountingNotImplementedError):
        service.validate_expense_input()
    with pytest.raises(AccountingNotImplementedError):
        service.record_expense_create_event()
    with pytest.raises(AccountingNotImplementedError):
        service.record_expense_update_event()
    with pytest.raises(AccountingNotImplementedError):
        service.record_expense_delete_event(1)
