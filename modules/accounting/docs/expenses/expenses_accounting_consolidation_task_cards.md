# Expenses Accounting Consolidation Task Cards

## Purpose

These cards consolidate current Expenses accounting behavior into `modules/accounting/` without changing behavior first. Current behavior is legacy behavior to characterize and preserve. These cards do not assert that current accounting is correct.

## Non-Goals

- No accounting correctness changes
- No final ledger implementation
- No schema redesign
- No ERP integration
- No UI redesign unless required for existing call-site wiring
- No invented payment, refund, or bank semantics

## Execution Rules

- Implement one card at a time.
- Add characterization tests before changing production call sites.
- Do not proceed to write-side cards until read-side cards are stable.
- Preserve current behavior.
- Route external modules through `AccountingService` only.
- Do not import `modules.accounting.current_rules.*` or `modules.accounting.ledger.*` from expense, reporting, dashboard, backup/restore, or repository modules.
- Update the migration log after every implemented card.
- Document unclear behavior instead of guessing.

## Migration Log Rule

Every implemented task card must append an entry to:

`modules/accounting/docs/expenses/accounting_consolidation_migration_log.md`

Use this format:

```markdown
## EX-ACC-000: Card title

- Migrated behavior:
- Original location(s):
- New accounting location(s):
- AccountingService API:
- Rewired call site(s):
- Tests added/updated:
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
```

## Recommended Implementation Order

1. EX-ACC-001: Verify Expense accounting facade guardrails
2. EX-ACC-002: Define Expense DTO/API contracts
3. EX-ACC-003: Consolidate expense row reads and screen totals
4. EX-ACC-004: Consolidate expense report summary and line reads
5. EX-ACC-005: Consolidate financial-report expense breakdown
6. EX-ACC-006: Consolidate dashboard expense totals and sales-dashboard expense dependency
7. EX-ACC-007: Consolidate expense create/update/delete writes
8. EX-ACC-008: Consolidate expense-category validation and lifecycle behavior
9. EX-ACC-009: Audit and document vendor/purchase overlap
10. EX-ACC-010: Cleanup migrated calculations and verify guardrails

## EX-ACC-001: Verify Expense accounting facade guardrails

### Goal

Confirm the accounting scaffold is ready for Expense migration and lock the rule that external modules call only `AccountingService`.

### Current behavior to preserve

No runtime behavior changes. Existing expense, reporting, dashboard, and backup/restore paths stay unchanged until their own cards migrate them.

### Target accounting module location

- `modules/accounting/service.py`
- `modules/accounting/__init__.py`
- `modules/accounting/current_rules/expense_rules.py`
- `tests/accounting/test_expense_accounting_guardrails.py`

### TDD plan

1. Red:
   - Add guardrail tests for expense, reporting, dashboard, backup/restore, and repository modules.
2. Green:
   - Make tests pass without changing business behavior.
3. Refactor:
   - Keep the import-scan helper small.

### Tests to add or update

- `tests/accounting/test_expense_accounting_guardrails.py::test_expense_modules_do_not_import_accounting_internals`
- `tests/accounting/test_expense_accounting_guardrails.py::test_accounting_service_is_public_expense_facade`

### Implementation steps

1. Inspect imports in `modules/expense`, `modules/reporting`, `modules/dashboard`, `modules/backup_restore`, and `database/repositories`.
2. Add an AST-based guardrail test modeled on existing vendor/customer accounting guardrail tests.
3. Assert only `AccountingService` is exposed as the public facade for future Expense accounting calls.
4. Do not rewire production call sites in this card.

### Acceptance criteria

- [ ] Guardrail tests exist.
- [ ] Tests prove external modules do not import accounting internals.
- [ ] No production behavior changes.
- [ ] Migration log entry is appended after implementation.

## EX-ACC-002: Define Expense DTO/API contracts

### Goal

Add the smallest Expense DTOs and `AccountingService` method signatures needed by later cards, with unmigrated methods raising `AccountingNotImplementedError`.

### Current behavior to preserve

No current app call site behavior changes. New methods fail loudly until their slice is migrated.

### Target accounting module location

- `modules/accounting/dto.py`
- `modules/accounting/service.py`
- `modules/accounting/__init__.py`
- `modules/accounting/current_rules/expense_rules.py`

### Proposed AccountingService API

```python
AccountingService.get_expense_financial_summary(expense_id: int) -> ExpenseFinancialSummary
AccountingService.list_expense_rows(...) -> tuple[ExpenseFinancialSummary, ...]
AccountingService.get_expense_screen_category_totals(...) -> tuple[ExpenseCategoryTotal, ...]
AccountingService.get_expense_report_category_totals(...) -> tuple[ExpenseCategoryTotal, ...]
AccountingService.get_expense_report_lines(...) -> tuple[ExpenseReportLine, ...]
AccountingService.get_dashboard_expense_total(date_from: str, date_to: str) -> Decimal
AccountingService.get_profit_loss_expense_summary(date_from: str, date_to: str) -> ExpenseProfitLossSummary
AccountingService.validate_expense_input(...) -> None
AccountingService.record_expense_create_event(...)
AccountingService.record_expense_update_event(...)
AccountingService.record_expense_delete_event(expense_id: int) -> None
```

### TDD plan

1. Red:
   - Add contract tests that instantiate `AccountingService`.
   - Assert new methods exist and raise `AccountingNotImplementedError`.
2. Green:
   - Add minimal DTO dataclasses and method stubs.
3. Refactor:
   - Remove any DTO not tied to a planned later card.

### Tests to add or update

- `tests/accounting/test_expense_accounting_contracts.py::test_expense_service_contract_methods_exist`
- `tests/accounting/test_expense_accounting_contracts.py::test_unmigrated_expense_methods_raise_not_implemented`
- `modules/accounting/test_accounting_scaffold.py`

### Acceptance criteria

- [ ] DTOs cover planned Expense read-side and write-side APIs.
- [ ] Unmigrated methods raise `AccountingNotImplementedError`.
- [ ] No repository, UI, or report behavior changes.

## EX-ACC-003: Consolidate expense row reads and screen totals

### Goal

Move current expense row reads and expense-screen category totals behind `AccountingService`, then rewire only the original expense-module call sites for that slice.

### Current behavior to preserve

- `ExpensesRepo.get_expense()`
- `ExpensesRepo.list_expenses()`
- `ExpensesRepo.search_expenses_adv()`
- `ExpensesRepo.total_by_category()`
- zero-total named categories and uncategorized handling must stay unchanged

### Target accounting module location

- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/service.py`
- `modules/accounting/dto.py`
- `database/repositories/expenses_repo.py`
- `modules/expense/controller.py`

### TDD plan

1. Red:
   - Add characterization tests for single-row reads, list/search behavior, and screen category totals.
2. Green:
   - Implement current-rules wrappers first.
   - Rewire repo/controller call sites through `AccountingService`.
3. Refactor:
   - Remove only duplication caused by this rewiring.

### Tests to add or update

- `tests/accounting/test_expense_row_reads.py`
- `tests/accounting/test_expense_screen_totals.py`

### Acceptance criteria

- [ ] Expense screen values match pre-migration behavior.
- [ ] Expense repo routes this slice through `AccountingService`.
- [ ] No report, dashboard, or write behavior changes.

## EX-ACC-004: Consolidate expense report summary and line reads

### Goal

Move expense report category totals and expense report lines behind `AccountingService`, then rewire expense reporting call sites.

### Current behavior to preserve

- `ReportingRepo.expense_summary_by_category()`
- `ReportingRepo.expense_lines()`
- PDF/export values in `modules/reporting/expense_reports.py`

### Target accounting module location

- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/service.py`
- `database/repositories/reporting_repo.py`
- `modules/reporting/expense_reports.py`

### TDD plan

1. Red:
   - Characterize report summary rows, line ordering, date filtering, category naming, and uncategorized handling.
2. Green:
   - Implement read-side wrappers and rewire reporting call sites.
3. Refactor:
   - Keep report and screen totals separate if queries differ.

### Tests to add or update

- `tests/accounting/test_expense_report_reads.py`

### Acceptance criteria

- [ ] Expense report tab values match pre-migration behavior.
- [ ] PDF/export payload stays unchanged.
- [ ] No write-side behavior changes.

## EX-ACC-005: Consolidate financial-report expense breakdown

### Goal

Move P&L expense-category summary behind `AccountingService`, then rewire financial-report callers.

### Current behavior to preserve

- `ReportingRepo.expenses_by_category()`
- expense block inside `modules/reporting/financial_reports.py::income_statement()`

### Target accounting module location

- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/service.py`
- `database/repositories/reporting_repo.py`
- `modules/reporting/financial_reports.py`

### TDD plan

1. Red:
   - Characterize income-statement expense rows and totals.
2. Green:
   - Implement service wrapper and rewire financial reports.
3. Refactor:
   - Keep this API separate from screen/report totals if behavior differs.

### Tests to add or update

- `tests/accounting/test_expense_profit_loss_summary.py`

### Acceptance criteria

- [ ] Income-statement expense output matches pre-migration behavior.
- [ ] No dashboard or write-side changes in this card.

## EX-ACC-006: Consolidate dashboard expense totals and sales-dashboard expense dependency

### Goal

Move dashboard expense-total reads behind `AccountingService`, including the expense slice currently embedded in `sales_rules.get_sales_dashboard_metrics()`.

### Current behavior to preserve

- `DashboardRepo.expenses_total()`
- expense fields inside `DashboardRepo.summary_metrics()`
- expense dependency inside `get_sales_dashboard_metrics()`

### Target accounting module location

- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/service.py`
- `database/repositories/dashboard_repo.py`
- `modules/accounting/current_rules/sales_rules.py`

### TDD plan

1. Red:
   - Characterize dashboard expense totals for default and filtered date ranges.
2. Green:
   - Extract only the expense slice and rewire callers through `AccountingService`.
3. Refactor:
   - Avoid broad dashboard cleanup in this card.

### Tests to add or update

- `tests/accounting/test_expense_dashboard_totals.py`

### Acceptance criteria

- [ ] Dashboard expense totals match pre-migration behavior.
- [ ] Sales dashboard metrics keep same expense contribution.

## EX-ACC-007: Consolidate expense create/update/delete writes

### Goal

Move current expense CRUD writes behind `AccountingService` after read-side parity is stable.

### Current behavior to preserve

- `ExpensesRepo.create_expense()`
- `ExpensesRepo.update_expense()`
- `ExpensesRepo.delete_expense()`
- hard-delete behavior stays unchanged
- current validation behavior stays unchanged

### Target accounting module location

- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/service.py`
- `modules/accounting/validators.py`
- `database/repositories/expenses_repo.py`

### TDD plan

1. Red:
   - Characterize create, update, delete, and validation failures.
2. Green:
   - Move writes behind `AccountingService`.
3. Refactor:
   - Remove only duplicate validation introduced by the migration if tests still prove parity.

### Tests to add or update

- `tests/accounting/test_expense_write_events.py`

### Acceptance criteria

- [ ] CRUD behavior matches pre-migration behavior.
- [ ] Hard delete remains hard delete.
- [ ] No payment or bank semantics are invented.

## EX-ACC-008: Consolidate expense-category validation and lifecycle behavior

### Goal

Move current category validation and lifecycle rules behind accounting-safe boundaries only where needed by migrated expense flows.

### Current behavior to preserve

- `ExpensesRepo.create_category()`
- `ExpensesRepo.update_category()`
- `ExpensesRepo.delete_category()`
- referenced categories still block delete

### Target accounting module location

- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/validators.py`
- `database/repositories/expenses_repo.py`
- `modules/expense/category_dialog.py`

### TDD plan

1. Red:
   - Characterize create, rename, delete, and delete-block behavior.
2. Green:
   - Centralize only the migrated validation/lifecycle slice.
3. Refactor:
   - Do not fold report or dashboard logic into this card.

### Tests to add or update

- `tests/accounting/test_expense_category_lifecycle.py`

### Acceptance criteria

- [ ] Category lifecycle behavior matches pre-migration behavior.
- [ ] No unrelated expense read/report logic is changed.

## EX-ACC-009: Audit and document vendor/purchase overlap

### Goal

Document overlap risk between free-text expenses and supplier-side costs without changing runtime behavior.

### Current behavior to preserve

No code behavior changes. This card is documentation and risk-audit only.

### Target accounting module location

- `modules/accounting/docs/expenses/`

### TDD plan

1. Red:
   - No runtime tests required unless a doc guardrail is added.
2. Green:
   - Add a focused overlap audit note with concrete code references.
3. Refactor:
   - None.

### Acceptance criteria

- [ ] Supplier-cost overlap is documented with source references.
- [ ] No production code changes.

## EX-ACC-010: Cleanup migrated calculations and verify guardrails

### Goal

Finish the Expense consolidation by removing only duplication made obsolete by migrated slices and by proving app modules use `AccountingService`.

### Current behavior to preserve

All previously characterized Expense behavior.

### Target accounting module location

- migrated expense call sites across `modules/expense`, `modules/reporting`, `modules/dashboard`, and `database/repositories`
- `tests/accounting/`

### TDD plan

1. Red:
   - Add or tighten final guardrail/parity tests.
2. Green:
   - Remove obsolete duplicate calculations only where migrated tests already prove parity.
3. Refactor:
   - Keep cleanup surgical.

### Tests to add or update

- final updates to existing `tests/accounting/test_expense_*`

### Acceptance criteria

- [ ] Expense, reporting, and dashboard slices use `AccountingService` for migrated behavior.
- [ ] Remaining duplicate math is either removed or explicitly documented.
- [ ] No correctness changes are folded into cleanup.
