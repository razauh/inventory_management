# Accounting Consolidation Migration Log

## Purpose

This file records Expense accounting behavior that has been migrated into `modules/accounting/`.

It is not a correctness document.
It does not claim migrated behavior is final or correct.
It records where legacy/current behavior moved and which application call sites now use `AccountingService`.

## Rules

- Add one entry after each completed Expense task card.
- State whether behavior changed. During consolidation, behavior should normally be "None intended."
- Record unresolved correctness questions for the later correction phase.
- Do not use this file to define final accounting rules.

## Entries

## EX-ACC-002: Define Expense DTO/API contracts

- Migrated behavior:
  - None. Contract definition card only.
- Original location(s):
  - N/A
- New accounting location(s):
  - `modules/accounting/dto.py` (new DTOs: `ExpenseFinancialSummary`, `ExpenseCategoryTotal`, `ExpenseReportLine`, `ExpenseProfitLossSummary`)
  - `modules/accounting/service.py` (new method stubs raising `AccountingNotImplementedError`)
  - `modules/accounting/__init__.py` (exports for new DTOs)
- AccountingService API:
  - `get_expense_financial_summary(expense_id: int) -> ExpenseFinancialSummary`
  - `list_expense_rows(...) -> tuple[ExpenseFinancialSummary, ...]`
  - `get_expense_screen_category_totals(...) -> tuple[ExpenseCategoryTotal, ...]`
  - `get_expense_report_category_totals(...) -> tuple[ExpenseCategoryTotal, ...]`
  - `get_expense_report_lines(...) -> tuple[ExpenseReportLine, ...]`
  - `get_dashboard_expense_total(date_from: str, date_to: str) -> Decimal`
  - `get_profit_loss_expense_summary(date_from: str, date_to: str) -> ExpenseProfitLossSummary`
  - `validate_expense_input(...) -> None`
  - `record_expense_create_event(...)`
  - `record_expense_update_event(...)`
  - `record_expense_delete_event(expense_id: int) -> None`
- Rewired call site(s):
  - None. No call sites rewired in this contracts card.
- Tests added/updated:
  - `tests/accounting/test_expense_accounting_contracts.py` (new)
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
  - Expense behavior is still managed in legacy locations (`ExpensesRepo`, `FinancialReports`, etc.). Call sites will be rewired in subsequent cards.


## EX-ACC-003: Consolidate expense row reads and screen totals

- Migrated behavior:
  - Single-row reads (`get_expense`), advanced search (`search_expenses_adv`), and screen-level category totals (`total_by_category`).
- Original location(s):
  - `database/repositories/expenses_repo.py`
- New accounting location(s):
  - `modules/accounting/current_rules/expense_rules.py` (new)
  - `modules/accounting/service.py` (implemented methods: `get_expense_financial_summary`, `list_expense_rows`, `get_expense_screen_category_totals`)
- Rewired call site(s):
  - `database/repositories/expenses_repo.py` (`get_expense`, `search_expenses_adv`, `total_by_category` now route through `AccountingService`)
  - `modules/expense/controller.py` (read calls rewired to use `AccountingService` directly)
- Tests added/updated:
  - `tests/accounting/test_expense_row_reads.py` (new)
  - `tests/accounting/test_expense_screen_totals.py` (new)
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
  - Return types of migrated methods are standardized to DTO dataclasses with `Decimal` values for financial amounts.


