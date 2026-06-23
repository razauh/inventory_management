# Expenses Accounting Consolidation Plan

## Purpose

This plan documents how current Expenses accounting behavior should move into `modules/accounting/`.

- No implementation is done in this document step.
- No production behavior is changed.
- No correctness decision is made.
- This plan exists to drive later TDD task cards.

## Current Repo State

- Vendor + Purchase consolidation already exists in `modules/accounting/`, with docs under `modules/accounting/docs/purchase_vendor/`.
- Customer + Sales consolidation already exists in `modules/accounting/`, with docs under `modules/accounting/docs/customer_sales/`.
- The live docs pattern in this worktree is subfolder-based, so Expenses docs should follow `modules/accounting/docs/expenses/`.
- Expenses should follow the same facade-first, current-rules-first, behavior-preserving pattern.
- Current Expenses behavior is legacy behavior and must be characterized before any correction work.

## Existing Accounting Module Pattern To Reuse

Repository inspection shows an established pattern already in use:

- Public facade: `modules/accounting/service.py` exposes `AccountingService`.
- Current behavior homes: `modules/accounting/current_rules/*.py` preserve current logic behind stable service methods.
- DTO boundary: `modules/accounting/dto.py` holds dataclasses for read and write contracts.
- Validation boundary: `modules/accounting/validators.py` holds metadata validation that mirrors current behavior.
- Report boundary: `modules/accounting/reports/` holds read-side report models where a full report slice was migrated.
- Migration log: implemented cards append entries to a consolidation migration log.
- Test pattern: `tests/accounting/test_vendor_purchase_*` and `tests/accounting/test_customer_sales_*` characterize current behavior first, then prove rewiring parity.
- Call-site rewiring style: controllers, repos, dashboard, and reporting modules instantiate `AccountingService(conn)` and delegate there; they do not import `current_rules` directly.
- Guardrails: `AGENTS.md` requires behavior preservation first, surgical changes, no silent accounting corrections, and centralization through `modules/accounting/service.py`.

Expenses should align with the same design:

- add DTOs only for actual expense slices,
- extract current behavior into `current_rules/expense_rules.py`,
- rewire callers through `AccountingService`,
- update the migration log only during implementation cards,
- keep schema, UI, and repository behavior unchanged until each slice is characterized.

## Expense Code Areas Inspected

Accounting module and consolidation references inspected:

- `modules/accounting/service.py`
- `modules/accounting/dto.py`
- `modules/accounting/__init__.py`
- `modules/accounting/validators.py`
- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/test_accounting_scaffold.py`
- `modules/accounting/docs/purchase_vendor/accounting_module_scaffold.md`
- `modules/accounting/docs/purchase_vendor/accounting_current_rules_inventory.md`
- `modules/accounting/docs/purchase_vendor/vendor_purchase_accounting_consolidation_task_cards.md`
- `modules/accounting/docs/purchase_vendor/vendor_purchase_accounting_references_audit.md`
- `modules/accounting/docs/customer_sales/customer_sales_accounting_consolidation_plan.md`
- `modules/accounting/docs/customer_sales/customer_sales_accounting_consolidation_task_cards.md`
- `modules/accounting/docs/customer_sales/accounting_consolidation_migration_log.md`

Expense module and repo files inspected:

- `database/schema.py`
- `database/repositories/expenses_repo.py`
- `modules/expense/controller.py`
- `modules/expense/form.py`
- `modules/expense/model.py`
- `modules/expense/view.py`
- `modules/expense/category_dialog.py`
- `tests/expense/test_expense_popup_toast_migration.py`

Reporting, dashboard, and display files inspected:

- `database/repositories/reporting_repo.py`
- `database/repositories/dashboard_repo.py`
- `modules/reporting/expense_reports.py`
- `modules/reporting/financial_reports.py`
- `modules/reporting/controller.py`
- `modules/reporting/model.py`
- `modules/dashboard/controller.py`
- `modules/dashboard/model.py`
- `modules/dashboard/view.py`

Backup/restore and purge files inspected:

- `modules/backup_restore/service.py`
- `modules/backup_restore/controller.py`
- `modules/backup_restore/views.py`
- `modules/backup_restore/test_purge_data.py`
- `tests/backup_restore/*`

Important inspected files with no relevant expense accounting behavior found:

- `modules/accounting/current_rules/expense_rules.py` is only a placeholder docstring.
- `resources/templates/reports/expense_summary.html` exists but is empty.
- No recurring-expense module was found.
- No expense payment table, expense bank-account field, expense payment-status field, or expense refund table was found in `database/schema.py`.
- No expense-specific import/export writer was found beyond report PDF export and full DB backup/restore.

## Expense Accounting Areas Identified

### Expense creation and update

- Current expense rows store only `description`, `amount`, `date`, and `category_id`.
- Validation is split between `modules/expense/form.py` and `database/repositories/expenses_repo.py`.
- No vendor, supplier, bank account, payment method, tax, attachment, paid-state, or receipt link is stored on the current `expenses` table.

### Expense deletion, cancellation, reversal

- `ExpensesRepo.delete_expense()` hard-deletes the row.
- No soft-delete path was found.
- No expense-specific bank or cash reversal exists because no expense payment ledger was found.

### Expense categories

- Category CRUD lives in `ExpensesRepo` and `CategoryDialog`.
- Category delete is blocked when expenses still reference it.
- Category totals are calculated in multiple places with slightly different query shapes.

### Payment behavior

- No current expense payment workflow was found.
- No expense payment method, cleared/pending/bounced state, or bank destination metadata exists in schema or expense UI.
- Any later expense-payment consolidation must first confirm whether current business behavior is simply "expense row implies recognized expense" with no cash/bank posting.

### Bank/cash effects

- No direct expense-to-bank or expense-to-cash write path was found.
- Dashboard and financial reports subtract expense totals from profit, but they do not derive expense bank movements.

### Reports, dashboards, and exports

- Expense module screen shows list rows and totals by category.
- Expense reporting tab shows summary by category and raw lines.
- Financial reports include expense category totals in the income statement.
- Dashboard subtracts total expenses in gross/net calculations and KPI summaries.
- Report PDF export exists in `modules/reporting/expense_reports.py`.

### Validation and status logic

- Amount must be positive in both UI and repo.
- Description is required in both UI and repo.
- Date must be present and ISO-valid in repo.
- Category is optional.
- No payment-state or bank-state validations were found for expenses.

## Current Source-Of-Truth Candidates

- Expense amount/date/description/category link:
  - storage: `database/schema.py` `expenses`
  - writes: `database/repositories/expenses_repo.py`
- Expense detail reads and search/filter behavior:
  - `ExpensesRepo.list_expenses()`
  - `ExpensesRepo.search_expenses_adv()`
  - `ExpensesRepo.get_expense()`
- Expense screen category totals:
  - `ExpensesRepo.total_by_category()`
- Expense report category totals and expense lines:
  - `ReportingRepo.expense_summary_by_category()`
  - `ReportingRepo.expense_lines()`
- Profit/loss expense totals:
  - `ReportingRepo.expenses_by_category()`
  - `FinancialReports.income_statement()`
- Dashboard total expenses:
  - `DashboardRepo.summary_metrics()`
  - `DashboardRepo.expenses_total()`
  - `modules/accounting/current_rules/sales_rules.py::get_sales_dashboard_metrics()`
- Delete behavior:
  - `ExpensesRepo.delete_expense()`
- Purge behavior:
  - `modules/backup_restore/service.py::purge_transactional_data()` deletes `expenses` rows but keeps `expense_categories`

## Display-Only And Derived References

These places display or consume expense accounting values but should not own long-term accounting logic:

- `modules/expense/model.py`
- `modules/expense/view.py`
- `modules/reporting/model.py`
- `modules/reporting/expense_reports.py`
- `modules/reporting/financial_reports.py`
- `modules/dashboard/view.py`
- `modules/dashboard/controller.py`
- `modules/dashboard/model.py`
- `modules/reporting/controller.py`

## Write-Side Accounting Events

- Expense creation:
  - `ExpensesRepo.create_expense()`
  - likely future API: `AccountingService.record_expense_create_event(...)`
- Expense update:
  - `ExpensesRepo.update_expense()`
  - likely future API: `AccountingService.record_expense_update_event(...)`
- Expense deletion:
  - `ExpensesRepo.delete_expense()`
  - likely future API: `AccountingService.record_expense_delete_event(expense_id)`
- Expense category lifecycle:
  - `ExpensesRepo.create_category()`
  - `ExpensesRepo.update_category()`
  - `ExpensesRepo.delete_category()`
- Purge:
  - `modules/backup_restore/service.py::purge_transactional_data()`

No current write-side events were found for expense payment, refund, bank/cash movement, recurring generation, or import.

## Read-Side Accounting Queries

- Expense row reads for the expense screen:
  - `ExpensesRepo.list_expenses()`
  - `ExpensesRepo.search_expenses_adv()`
  - `ExpensesRepo.get_expense()`
- Expense screen totals by category:
  - `ExpensesRepo.total_by_category()`
- Expense reporting summary by category:
  - `ReportingRepo.expense_summary_by_category()`
- Expense reporting line items:
  - `ReportingRepo.expense_lines()`
- P&L expense breakdown:
  - `ReportingRepo.expenses_by_category()`
  - `FinancialReports.income_statement()`
- Dashboard total expenses:
  - `DashboardRepo.summary_metrics()`
  - `DashboardRepo.expenses_total()`
  - `sales_rules.get_sales_dashboard_metrics()`

No current read-side queries were found for expense payment status, expense cash/bank totals, or cleared/pending/bounced state.

## Proposed AccountingService API Expansion

Add later, not in this doc task:

```python
AccountingService.get_expense_financial_summary(expense_id: int)
AccountingService.list_expense_rows(...)
AccountingService.get_expense_screen_category_totals(...)
AccountingService.get_expense_report_category_totals(...)
AccountingService.get_expense_report_lines(...)
AccountingService.get_dashboard_expense_total(date_from: str, date_to: str)
AccountingService.get_profit_loss_expense_summary(date_from: str, date_to: str)
AccountingService.validate_expense_input(...)
AccountingService.record_expense_create_event(...)
AccountingService.record_expense_update_event(...)
AccountingService.record_expense_delete_event(expense_id: int)
```

## Proposed Target Accounting Module Locations

- `modules/accounting/service.py`
- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/dto.py`
- `modules/accounting/validators.py`
- `modules/accounting/docs/expenses/accounting_consolidation_migration_log.md`
- `modules/accounting/docs/expenses/expenses_accounting_consolidation_plan.md`
- `modules/accounting/docs/expenses/expenses_accounting_consolidation_task_cards.md`

## Recommended Consolidation Phases

### Phase 0: Foundation alignment

- Confirm Expenses follow the same guardrail, DTO, migration-log, and test naming pattern as other accounting slices.
- Keep external modules calling only `AccountingService`.

### Phase 1: Read-only expense financial summaries

- Move single-expense read behavior and filter/list row read behavior behind `AccountingService`.
- Preserve current amount, date, category, and description behavior exactly.

### Phase 2: Read-only expense totals and category totals

- Move `ExpensesRepo.total_by_category()` first.
- Move expense report category totals and line reads second.
- Keep screen totals and report totals as separate APIs if behavior differs.

### Phase 3: Display/report/dashboard/export rewiring

- Rewire expense screen totals.
- Rewire expense reports tab.
- Rewire financial-report expense block.
- Rewire dashboard expense totals and the expense slice of `get_sales_dashboard_metrics()`.

### Phase 4: Expense payment current behavior

- Manual-review gate.
- Do not invent payment-status or payment-method APIs unless later investigation finds hidden current behavior.

### Phase 5: Bank/cash side effects

- Manual-review gate.
- If a later slice proves expense rows are expected to create cash/bank movements, characterize that behavior first.

### Phase 6: Expense update/delete behavior

- Move current create/update/delete writes behind `AccountingService` after read-side parity is stable.
- Preserve hard-delete behavior and existing validation.

### Phase 7: Vendor/purchase overlap

- Investigate purchase freight, extra charges, and supplier-cost overlap before changing accounting boundaries.

### Phase 8: Profit/loss and dashboard reporting

- Consolidate expense contribution to P&L and dashboard metrics after expense report reads are stable.

### Phase 9: Cleanup and guardrail verification

- Ensure expense, reporting, and dashboard modules call `AccountingService`.
- Ensure duplicated expense math is no longer scattered after migration.
- Document unresolved correctness issues without fixing them.

## Recommended Future Task Card Categories

- `EX-ACC-001: Verify Expense accounting facade guardrails`
- `EX-ACC-002: Define Expense DTO/API contracts`
- `EX-ACC-003: Consolidate expense row reads and screen totals`
- `EX-ACC-004: Consolidate expense report summary and line reads`
- `EX-ACC-005: Consolidate financial-report expense breakdown`
- `EX-ACC-006: Consolidate dashboard expense totals and sales-dashboard expense dependency`
- `EX-ACC-007: Consolidate expense create/update/delete writes`
- `EX-ACC-008: Consolidate expense-category validation and lifecycle behavior`
- `EX-ACC-009: Audit and document vendor/purchase overlap`
- `EX-ACC-010: Cleanup migrated calculations and verify guardrails`

## TDD Strategy For Later Task Cards

- Characterization tests first.
- Behavior-preserving consolidation second.
- No correctness changes inside migration cards.
- Separate read-side and write-side tests.
- Use small SQLite fixture setups that mimic the exact current schema behavior being migrated.
- Keep database isolation per test with focused fixture DBs or in-memory DBs.
- Append one migration-log entry after each implemented card.
- If current bugs are already present, capture them as current behavior first and defer correction to a later explicit card.

Current gap from repo inspection:

- expense UI toast tests exist,
- expense accounting characterization tests do not exist yet.

## Risk Analysis

- Duplicated totals logic:
  - risky because totals already exist in `ExpensesRepo`, `ReportingRepo`, `DashboardRepo`, and `sales_rules.get_sales_dashboard_metrics()`
- Screen totals versus report totals mismatch:
  - risky because current queries are not identical and may differ on zero-total categories or uncategorized rows
- No expense payment/bank model found:
  - risky because inventing one during consolidation would change business behavior
- Profit/loss and dashboard dependency hidden in sales rules:
  - risky because expense totals are currently embedded in `get_sales_dashboard_metrics()`
- Purge deletes expenses but keeps categories:
  - risky because write-side migration must not break purge expectations

## Open Questions

- Are users relying on any manual workflow where "expenses" imply cash or bank posting even though code does not store it?
- Are purchase-side freight or extra charges intentionally kept out of the expense module, or only not yet modeled?
- Is `resources/templates/reports/expense_summary.html` dead code or a planned report template?
- Are there untracked local docs that describe expense import/export or recurring-expense behavior?

## Non-Goals

- No accounting correction yet.
- No final double-entry ledger implementation.
- No chart-of-accounts redesign.
- No ERP integration.
- No UI redesign.
- No schema change unless a later approved card explicitly requires it.
- No behavior changes without separate approval.
- No invented expense payment, refund, or bank semantics.

## Recommended Next Step

The next step after this plan is:

- create TDD-based task cards for Expense accounting consolidation,
- keep one card per slice,
- rewire only the original call sites for that slice,
- preserve current behavior,
- update `modules/accounting/docs/expenses/accounting_consolidation_migration_log.md` after each completed card.

## Final Confirmation

- Planning only.
- No production behavior changed.
- No accounting implementation performed here.
- This plan is ready to drive the next task-card step.
