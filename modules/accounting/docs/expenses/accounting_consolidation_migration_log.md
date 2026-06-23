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


## EX-ACC-004: Consolidate expense report summary and line reads

- Migrated behavior:
  - Expense report category totals (`expense_summary_by_category`) and expense report raw lines (`expense_lines`).
- Original location(s):
  - `database/repositories/reporting_repo.py`
- New accounting location(s):
  - `modules/accounting/current_rules/expense_rules.py` (methods: `get_expense_report_category_totals`, `get_expense_report_lines`)
  - `modules/accounting/service.py` (implemented methods: `get_expense_report_category_totals`, `get_expense_report_lines`)
- Rewired call site(s):
  - `database/repositories/reporting_repo.py` (`expense_summary_by_category`, `expense_summary_by_category_iter`, `expense_lines`, `expense_lines_iter` now route through `AccountingService`)
  - `modules/reporting/expense_reports.py` (read calls rewired to use `AccountingService` directly)
- Tests added/updated:
  - `tests/accounting/test_expense_report_reads.py` (new)
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
  - None.


## EX-ACC-005: Consolidate expense Profit & Loss breakdown

- Migrated behavior:
  - Detailed expense totals by category for P&L middle block (`expenses_by_category`).
- Original location(s):
  - `database/repositories/reporting_repo.py`
- New accounting location(s):
  - `modules/accounting/current_rules/expense_rules.py` (method: `get_profit_loss_expense_summary`)
  - `modules/accounting/service.py` (implemented method: `get_profit_loss_expense_summary`)
- Rewired call site(s):
  - `database/repositories/reporting_repo.py` (`expenses_by_category` now routes through `AccountingService`)
  - `modules/reporting/financial_reports.py` (read calls rewired to use `AccountingService` directly)
- Tests added/updated:
  - `tests/accounting/test_expense_profit_loss_summary.py` (new)
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
  - None.


## EX-ACC-006: Consolidate dashboard expense totals and sales-dashboard expense dependency

- Migrated behavior:
  - Dashboard expense total reads (`expenses_total`) and the expense total dependency inside sales dashboard metrics (`get_sales_dashboard_metrics`).
- Original location(s):
  - `database/repositories/dashboard_repo.py`
  - `modules/accounting/current_rules/sales_rules.py`
- New accounting location(s):
  - `modules/accounting/current_rules/expense_rules.py` (method: `get_dashboard_expense_total`)
  - `modules/accounting/service.py` (implemented method: `get_dashboard_expense_total`)
- Rewired call site(s):
  - `database/repositories/dashboard_repo.py` (`expenses_total` and `summary_metrics` now route through `AccountingService`)
  - `modules/accounting/current_rules/sales_rules.py` (`get_sales_dashboard_metrics` now pre-fetches and passes expense totals to SQL parameter)
- Tests added/updated:
  - `tests/accounting/test_expense_dashboard_totals.py` (new)
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
  - None.


## EX-ACC-007: Consolidate expense create/update/delete writes

- Migrated behavior:
  - Expense CRUD write operations (create, update, delete) and validation logic.
- Original location(s):
  - `database/repositories/expenses_repo.py`
- New accounting location(s):
  - `modules/accounting/validators.py` (method: `validate_expense_input`)
  - `modules/accounting/current_rules/expense_rules.py` (methods: `record_expense_create_event`, `record_expense_update_event`, `record_expense_delete_event`)
  - `modules/accounting/service.py` (implemented methods: `validate_expense_input`, `record_expense_create_event`, `record_expense_update_event`, `record_expense_delete_event`)
- Rewired call site(s):
  - `database/repositories/expenses_repo.py` (`create_expense`, `update_expense`, and `delete_expense` now delegate to `AccountingService`)
- Tests added/updated:
  - `tests/accounting/test_expense_write_events.py` (new)
  - `tests/accounting/test_expense_accounting_contracts.py` (updated)
- Behavior change:
  - None.
- Notes / unresolved correctness questions:
  - None.



