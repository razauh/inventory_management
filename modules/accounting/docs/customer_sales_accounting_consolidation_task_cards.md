# Customer + Sales Accounting Consolidation Task Cards

## Purpose

These cards consolidate current Customer + Sales accounting behavior into `modules/accounting/` without changing behavior. Current behavior is legacy behavior to characterize and preserve first. These cards do not assert that current accounting is correct.

## Non-Goals

- No accounting correctness changes
- No final double-entry ledger implementation
- No schema redesign
- No ERP integration
- No UI redesign unless required for existing call-site wiring
- No business-rule invention

## Execution Rules

- Implement one card at a time.
- Run tests after every card.
- Commit after every successful card.
- Do not combine unrelated cards.
- Do not proceed to write-side cards until read-side cards are stable.
- Preserve current behavior.
- Document unresolved behavior instead of guessing.
- Update the migration log after every implemented card.
- Other modules must call `AccountingService`, not low-level accounting internals.
- Customer/Sales/UI modules must not import directly from:
  - `modules.accounting.ledger.*`
  - `modules.accounting.current_rules.*`

## Migration Log Rule

Every implemented task card must append an entry to:

`modules/accounting/docs/accounting_consolidation_migration_log.md`

This is required even if the implementation is small. The log must explain what accounting task was migrated and where it now lives.

## Recommended Implementation Order

1. CS-ACC-001: Verify Customer + Sales accounting facade guardrails
2. CS-ACC-002: Define Customer + Sales accounting DTO/API contracts
3. CS-ACC-003: Consolidate sale totals and discount summaries
4. CS-ACC-004: Consolidate sale outstanding and receivable position
5. CS-ACC-005: Consolidate sale payment status rollups
6. CS-ACC-006: Consolidate customer credit balance and open receivables
7. CS-ACC-007: Consolidate customer statement/history read model
8. CS-ACC-008: Rewire sales and customer display panels
9. CS-ACC-009: Consolidate sale invoice and quotation financial sourcing
10. CS-ACC-010: Consolidate sales, customer, dashboard, and export financial reads
11. CS-ACC-011: Consolidate customer payment history read model
12. CS-ACC-012: Consolidate customer payment write and clearing behavior
13. CS-ACC-013: Consolidate customer advance and credit grant behavior
14. CS-ACC-014: Consolidate customer credit application behavior
15. CS-ACC-015: Consolidate sale return financial behavior
16. CS-ACC-016: Consolidate customer refund behavior
17. CS-ACC-017: Consolidate bank/cash movements from customer and sales flows
18. CS-ACC-018: Consolidate sale inventory, COGS, margin, and profit effects
19. CS-ACC-019: Consolidate quotation totals, status, and conversion behavior
20. CS-ACC-020: Cleanup migrated calculations and enforce guardrails

## CS-ACC-001: Verify Customer + Sales accounting facade guardrails

### Goal
Confirm the accounting scaffold is ready for Customer + Sales migration and lock the rule that external modules call only `AccountingService`.

### Why this task exists
The plan shows Customer + Sales behavior spread across schema, repositories, customer UI, sales UI, reports, dashboards, templates, and inventory flows. This card reduces migration risk before any behavior slice moves. It mirrors the Vendor + Purchase guardrail pattern.

### Source references from plan
- Current Repo State: `AccountingService`, `current_rules`, DTOs, validators, and Vendor/Purchase guardrail pattern.
- Recommended Consolidation Phases: Foundation Alignment.
- Manual Review Before Task Cards: deleted docs versus `sales_vendor/` copies.

### Source code references to verify
- `modules/accounting/service.py`
- `modules/accounting/__init__.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `tests/accounting/test_vendor_purchase_accounting_guardrails.py`
- `modules/customer/`
- `modules/sales/`
- `modules/reporting/`
- `modules/dashboard/`
- `database/repositories/`
- `widgets/`

### Current behavior to preserve
No runtime behavior changes. Existing Customer + Sales call sites keep their current repository/UI/report paths until their specific card migrates them.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/__init__.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `tests/accounting/test_customer_sales_accounting_guardrails.py`

### Proposed AccountingService API
No business methods are implemented in this card. Existing placeholders remain:

```python
AccountingService.get_customer_balance(customer_id: int) -> None
AccountingService.get_sale_outstanding(sale_id: int) -> None
AccountingService.get_customer_credit_balance(customer_id: int) -> None
AccountingService.record_customer_receipt_event(*args, **kwargs) -> None
AccountingService.record_sale_return_event(*args, **kwargs) -> None
```

### Original call sites to rewire
None in this foundation card. This is the setup exception; later behavior cards must rewire concrete call sites through `AccountingService`.

### TDD plan
1. Red:
   * Add guardrail tests for Customer + Sales modules.
   * Tests should fail if customer, sales, reporting, dashboard, repository, inventory, widget, or template-support Python code imports `modules.accounting.current_rules` or `modules.accounting.ledger` directly.
2. Green:
   * Keep production behavior unchanged.
   * Make tests pass only by matching current import state or by removing any forbidden direct accounting-internal import if found.
3. Refactor:
   * Keep test helper small.
   * Do not touch business behavior.

### Tests to add or update
- `tests/accounting/test_customer_sales_accounting_guardrails.py::test_customer_sales_modules_do_not_import_accounting_internals`
- `tests/accounting/test_customer_sales_accounting_guardrails.py::test_accounting_service_is_public_customer_sales_facade`

### Implementation steps
1. Inspect imports in `modules/customer`, `modules/sales`, `modules/reporting`, `modules/dashboard`, `database/repositories`, `modules/inventory`, and `widgets`.
2. Add an AST-based guardrail test modeled on `tests/accounting/test_vendor_purchase_accounting_guardrails.py`.
3. Assert only `AccountingService` is exposed as the public facade for future Customer + Sales accounting calls.
4. Do not add business accounting methods beyond existing placeholders.
5. Do not rewire production call sites in this card.

### Migration log update
After implementing this card, append a short entry to:

`modules/accounting/docs/accounting_consolidation_migration_log.md`

Use this format:

```markdown
## CS-ACC-001: Verify Customer + Sales accounting facade guardrails

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

### Behavior-preservation checks
- Guardrail tests pass.
- No repository, UI, schema, trigger, view, or report behavior changes.
- Existing Customer + Sales workflows still use their old paths.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No Customer + Sales business logic migration.

### Acceptance criteria
- [ ] Guardrail tests exist for Customer + Sales areas.
- [ ] Tests prove external modules do not import accounting internals.
- [ ] No production behavior changes.
- [ ] Migration log entry is appended.

### Rollback notes
Delete the new guardrail test file and migration log entry. No data rollback is needed.

### Dependencies
None.

### Follow-up tasks unlocked
- CS-ACC-002

## CS-ACC-002: Define Customer + Sales accounting DTO/API contracts

### Goal
Add the smallest Customer + Sales DTOs and `AccountingService` method signatures needed by later cards, with unmigrated methods still raising `AccountingNotImplementedError`.

### Why this task exists
Later cards need stable names and return shapes. This avoids each card inventing its own customer/sale accounting contract. It mirrors the Vendor + Purchase DTO/API pattern.

### Source references from plan
- Proposed AccountingService Expansion.
- Recommended Consolidation Phases: Foundation Alignment.
- Accounting Areas To Consolidate.

### Source code references to verify
- `modules/accounting/service.py`
- `modules/accounting/dto.py`
- `modules/accounting/exceptions.py`
- `modules/accounting/__init__.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/test_accounting_scaffold.py`
- `tests/accounting/test_vendor_purchase_accounting_contracts.py`

### Current behavior to preserve
No current app call site behavior changes. New methods that are not migrated yet fail loudly with the existing accounting not-implemented exception.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/dto.py`
- `modules/accounting/__init__.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`

### Proposed AccountingService API
```python
AccountingService.get_sale_totals(sale_id: int | str) -> SaleTotals
AccountingService.get_sale_financial_summary(sale_id: int | str) -> SaleFinancialSummary
AccountingService.get_sale_outstanding(sale_id: int | str) -> SaleOutstanding
AccountingService.get_sale_payment_status(sale_id: int | str) -> SalePaymentStatus
AccountingService.get_sale_payment_history(sale_id: int | str) -> tuple[SalePaymentRow, ...]
AccountingService.get_customer_credit_balance(customer_id: int) -> CustomerBalance
AccountingService.get_customer_open_sales(customer_id: int) -> tuple[CustomerOpenSale, ...]
AccountingService.get_customer_statement(customer_id: int, start_date: str | None = None, end_date: str | None = None) -> CustomerStatement
AccountingService.get_sale_invoice_financials(sale_id: int | str) -> SaleInvoiceFinancials
AccountingService.get_quotation_financials(quotation_id: int | str) -> QuotationFinancials
```

### Original call sites to rewire
None in this contract card. This is a setup exception; later behavior cards must rewire concrete call sites.

### TDD plan
1. Red:
   * Add contract tests that instantiate `AccountingService`.
   * Assert new methods exist.
   * Assert unmigrated methods raise `AccountingNotImplementedError`.
2. Green:
   * Add minimal DTO dataclasses using `Decimal` for money.
   * Add method stubs to `AccountingService`.
3. Refactor:
   * Remove any DTO not tied to a named later card.
   * Keep DTOs boring and data-only.

### Tests to add or update
- `tests/accounting/test_customer_sales_accounting_contracts.py::test_customer_sales_service_contract_methods_exist`
- `tests/accounting/test_customer_sales_accounting_contracts.py::test_unmigrated_customer_sales_methods_raise_not_implemented`
- `modules/accounting/test_accounting_scaffold.py::test_accounting_dtos_are_importable`

### Implementation steps
1. Compare Vendor + Purchase DTOs and naming in `modules/accounting/dto.py`.
2. Add only DTOs required by the Customer + Sales cards.
3. Add service stubs with return annotations.
4. Export DTOs from `modules/accounting/__init__.py` if that is how Vendor + Purchase DTOs are exported.
5. Do not import repositories yet.
6. Do not wire app code yet.

### Migration log update
After implementing this card, append a short entry to:

```markdown
## CS-ACC-002: Define Customer + Sales accounting DTO/API contracts

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

### Behavior-preservation checks
- Contract tests pass.
- No Customer + Sales production call sites call the new stubs.
- No database, UI, report, or repository behavior changes.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No implementation of calculations.

### Acceptance criteria
- [ ] DTOs cover planned Customer + Sales slices.
- [ ] Service methods exist.
- [ ] Unmigrated service methods raise `AccountingNotImplementedError`.
- [ ] Migration log entry is appended.

### Rollback notes
Remove added DTOs, exports, service stubs, contract tests, and migration log entry.

### Dependencies
- CS-ACC-001

### Follow-up tasks unlocked
- CS-ACC-003
- CS-ACC-004
- CS-ACC-006
- CS-ACC-007

## CS-ACC-003: Consolidate sale totals and discount summaries

### Goal
Move current sale subtotal, item discount, order discount, returned value, and net sale total reads behind `AccountingService`, then rewire original read call sites for this slice.

### Why this task exists
Sale totals feed outstanding, status, returns, invoices, reports, dashboards, and profit. This read-only slice is a low-risk base for later cards.

### Source references from plan
- Accounting Areas To Consolidate: sale totals, discounts, reports, invoices.
- Recommended Consolidation Phases: Read-Only Sale Financial Summaries.
- Source Areas To Preserve First: `sales`, `sale_items`, `sale_detailed_totals`.

### Source code references to verify
- `database/schema.py`: `sales`, `sale_items`, `sale_detailed_totals`.
- `database/repositories/sales_repo.py::get_sale_totals`
- `database/repositories/sales_repo.py::get_sale_detail_summary`
- `database/repositories/sales_repo.py::get_sale_detail_snapshot`
- `modules/sales/form.py`
- `modules/sales/items.py`
- `modules/sales/controller.py`
- `resources/templates/invoices/sale_invoice.html`
- `resources/templates/invoices/quotation_invoice.html`

### Current behavior to preserve
Totals must match current SQL views and `SalesRepo` outputs, including current item discount, order discount, return-value, and stored header total behavior. Do not decide whether those totals are correct.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_sale_totals(sale_id: int | str) -> SaleTotals
AccountingService.preview_sale_total(items: tuple[SaleTotalInputLine, ...], order_discount: Decimal) -> SaleTotals
```

### Original call sites to rewire
- `database/repositories/sales_repo.py::get_sale_totals`
- `database/repositories/sales_repo.py::get_sale_detail_summary`
- `database/repositories/sales_repo.py::get_sale_detail_snapshot`
- `modules/sales/controller.py` sale total reads used for details and invoice data.
- `modules/sales/form.py` and `modules/sales/items.py` only if preview math is duplicated and can be safely routed without changing UI behavior.

### TDD plan
1. Red:
   * Add characterization tests comparing `AccountingService.get_sale_totals` to `sale_detailed_totals` and `SalesRepo.get_sale_totals`.
   * Include item discount, order discount, and sale return value if existing fixtures support it.
2. Green:
   * Wrap current SQL/repository behavior in `current_rules/sales_rules.py`.
   * Rewire the read call sites for this slice to `AccountingService`.
3. Refactor:
   * Remove only duplicate total code made obsolete by the service route.
   * Do not correct rounding or discount behavior.

### Tests to add or update
- `tests/accounting/test_customer_sales_sale_totals.py::test_sale_totals_match_current_view`
- `tests/accounting/test_customer_sales_sale_totals.py::test_sale_totals_preserve_item_and_order_discount_behavior`
- `tests/accounting/test_customer_sales_sale_totals.py::test_sales_repo_routes_sale_totals_through_accounting_service`

### Implementation steps
1. Build isolated SQLite fixture with sale items and discounts.
2. Capture current `sale_detailed_totals` and `SalesRepo.get_sale_totals` output.
3. Add `SaleTotals` and optional `SaleTotalInputLine` DTOs if not already added.
4. Implement current-rule wrapper in `sales_rules.py`.
5. Add `AccountingService.get_sale_totals`.
6. Rewire `SalesRepo.get_sale_totals` and dependent detail reads to use the service.
7. Leave schema views and triggers intact.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-003: Consolidate sale totals and discount summaries

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

### Behavior-preservation checks
- Service output equals `sale_detailed_totals`.
- `SalesRepo.get_sale_totals` output is unchanged.
- Existing sale detail and invoice total values are unchanged.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No payment, credit, return settlement, or profit changes.

### Acceptance criteria
- [ ] Sale total service method exists.
- [ ] Current sale total behavior is characterized.
- [ ] Original read call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore call sites to direct `SalesRepo`/SQL reads, remove service wrapper/tests/DTOs for this slice, and remove the migration log entry.

### Dependencies
- CS-ACC-002

### Follow-up tasks unlocked
- CS-ACC-004
- CS-ACC-005
- CS-ACC-009
- CS-ACC-018

## CS-ACC-004: Consolidate sale outstanding and receivable position

### Goal
Move current sale outstanding, remaining due, canonical receivable total, paid amount, and applied credit reads behind `AccountingService`.

### Why this task exists
Receivable position is used by payments, credit application, invoices, customer lists, AR aging, and details. It must stabilize before write-side cards.

### Source references from plan
- Accounting Areas To Consolidate: customer receivables, due amount, sale outstanding.
- Recommended Consolidation Phases: Read-Only Sale Financial Summaries.
- Manual Review Before Task Cards: `posted` plus `cleared` versus `cleared` only differences.

### Source code references to verify
- `database/schema.py`: `sale_receivable_totals`
- `database/repositories/sales_repo.py::get_receivable_position`
- `database/repositories/sales_repo.py::get_sale_detail_summary`
- `database/repositories/sales_repo.py::get_sale_detail_snapshot`
- `database/repositories/customer_advances_repo.py::apply_credit_to_sale`
- `database/repositories/sale_payments_repo.py::record_payment_with_conn`
- `modules/sales/controller.py::_fetch_sale_financials`
- `modules/customer/controller.py::_eligible_sales_for_application`

### Current behavior to preserve
Outstanding and remaining due must match current `sale_receivable_totals`, `SalesRepo.get_receivable_position`, and existing clamp behavior. Preserve how paid amount and applied customer credit are included.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_sale_outstanding(sale_id: int | str) -> SaleOutstanding
AccountingService.get_sale_financial_summary(sale_id: int | str) -> SaleFinancialSummary
```

### Original call sites to rewire
- `database/repositories/sales_repo.py::get_receivable_position`
- `database/repositories/sales_repo.py::get_sale_detail_summary`
- `database/repositories/sales_repo.py::get_sale_detail_snapshot`
- `modules/sales/controller.py::_fetch_sale_financials`
- `modules/sales/controller.py::_financial_action_eligibility`
- `modules/customer/controller.py::_eligible_sales_for_application`
- `modules/customer/controller.py::_list_sales_for_customer`

### TDD plan
1. Red:
   * Add characterization tests comparing service output to `sale_receivable_totals` and `SalesRepo.get_receivable_position`.
   * Include unpaid, partial, paid, and credit-applied cases.
2. Green:
   * Wrap the current SQL in `sales_rules.py`.
   * Rewire original read call sites to the service.
3. Refactor:
   * Remove duplicate remaining-due calculations only where tests prove parity.
   * Do not change clamp, rounding, or posted/cleared assumptions.

### Tests to add or update
- `tests/accounting/test_customer_sales_sale_outstanding.py::test_sale_outstanding_matches_receivable_view`
- `tests/accounting/test_customer_sales_sale_outstanding.py::test_sale_financial_summary_matches_sales_repo`
- `tests/accounting/test_customer_sales_sale_outstanding.py::test_credit_applied_remaining_due_is_preserved`

### Implementation steps
1. Create fixture with sale, payment, and applied customer credit.
2. Capture `sale_receivable_totals` values.
3. Add `SaleOutstanding`/`SaleFinancialSummary` fields needed by current call sites.
4. Implement wrapper in `sales_rules.py`.
5. Add `AccountingService` methods.
6. Rewire repository/controller read call sites.
7. Leave payment write behavior untouched.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-004: Consolidate sale outstanding and receivable position

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

### Behavior-preservation checks
- Service output equals `sale_receivable_totals`.
- Rewired `SalesRepo` methods return the same dict fields and values.
- Customer credit application eligibility sees the same due values.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No customer payment writes.

### Acceptance criteria
- [ ] Sale outstanding service method exists.
- [ ] Current remaining-due behavior is characterized.
- [ ] Original read call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore direct SQL/repository reads, remove service methods/tests for this slice, and remove the migration log entry.

### Dependencies
- CS-ACC-003

### Follow-up tasks unlocked
- CS-ACC-005
- CS-ACC-006
- CS-ACC-012
- CS-ACC-014

## CS-ACC-005: Consolidate sale payment status rollups

### Goal
Move current sale `paid`, `unpaid`, and `partial` status calculation and header rollup refresh behind `AccountingService`.

### Why this task exists
Payment status logic exists in SQL triggers, `SalesRepo._refresh_sale_payment_status`, sales list queries, details, reports, and tests. This card isolates that behavior after totals/outstanding are stable.

### Source references from plan
- Accounting Areas To Consolidate: sale payment status and validation/status rules.
- Recommended Consolidation Phases: Read-only sale financial summaries.
- Manual Review Before Task Cards: duplicate status logic in triggers and `SalesRepo._refresh_sale_payment_status`.

### Source code references to verify
- `database/schema.py`: `trg_paid_from_sale_payments_*`, `trg_adv_applied_from_customer_*`
- `database/repositories/sales_repo.py::_refresh_sale_payment_status`
- `database/repositories/sales_repo.py::_sales_list_select_sql`
- `database/repositories/sale_payments_repo.py::record_payment_with_conn`
- `database/repositories/customer_advances_repo.py::apply_credit_to_sale`
- `modules/sales/model.py`
- `modules/sales/details.py`
- `tests/sales/test_sales_payment_status_colors.py`
- `tests/sales/test_sales_payment_button_state.py`
- `tests/reporting/test_sales_reports_historical_status.py`

### Current behavior to preserve
Status values remain exactly `paid`, `unpaid`, and `partial`. Header `paid_amount`, `advance_payment_applied`, and `payment_status` must update the same way current triggers and repository refreshes update them.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_sale_payment_status(sale_id: int | str) -> SalePaymentStatus
AccountingService.recalculate_sale_payment_status(sale_id: int | str) -> SalePaymentStatus
```

### Original call sites to rewire
- `database/repositories/sales_repo.py::_refresh_sale_payment_status`
- `database/repositories/sales_repo.py::_sales_list_select_sql` only where a Python status read exists and can be safely routed.
- `database/repositories/sale_payments_repo.py` refresh calls after payment state changes.
- `database/repositories/customer_advances_repo.py` refresh calls after credit application.
- `modules/sales/details.py` and `modules/sales/model.py` if they calculate or normalize status outside display formatting.

### TDD plan
1. Red:
   * Add characterization tests for unpaid, partial, fully paid by payment, fully paid by credit, and mixed payment/credit.
   * Assert service status matches current header fields and `SalesRepo` refresh behavior.
2. Green:
   * Wrap current status calculation and refresh behavior in `sales_rules.py`.
   * Rewire repository refresh call sites through `AccountingService`.
3. Refactor:
   * Remove duplicate Python status math only where tests prove parity.
   * Keep schema triggers intact.

### Tests to add or update
- `tests/accounting/test_customer_sales_payment_status.py::test_sale_payment_status_matches_header_rollup`
- `tests/accounting/test_customer_sales_payment_status.py::test_sale_payment_status_preserves_payment_and_credit_mix`
- `tests/accounting/test_customer_sales_payment_status.py::test_recalculate_sale_payment_status_preserves_sales_repo_behavior`

### Implementation steps
1. Inspect trigger behavior and `SalesRepo._refresh_sale_payment_status`.
2. Write tests that compare current header values before/after refresh.
3. Add `SalePaymentStatus` DTO if missing.
4. Implement current-rule functions in `sales_rules.py`.
5. Add `AccountingService` methods.
6. Rewire repository refresh points.
7. Do not remove database triggers.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-005: Consolidate sale payment status rollups

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

### Behavior-preservation checks
- Status outputs match current headers.
- Trigger-updated rows remain valid.
- Existing status colors/buttons see unchanged status strings.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No change to status labels.

### Acceptance criteria
- [ ] Status service methods exist.
- [ ] Current status behavior is characterized.
- [ ] Original refresh call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore direct `_refresh_sale_payment_status` implementation and remove service wrapper/tests/log entry.

### Dependencies
- CS-ACC-004

### Follow-up tasks unlocked
- CS-ACC-012
- CS-ACC-014
- CS-ACC-015

## CS-ACC-006: Consolidate customer credit balance and open receivables

### Goal
Move current customer credit balance, open sales, and receivable summary reads behind `AccountingService`.

### Why this task exists
Customer balance and open receivables feed the customer financial panel, credit application, customer statement, AR aging, and sales actions. This read-side slice should land before customer write-side credit behavior.

### Source references from plan
- Accounting Areas To Consolidate: customer balance and receivables; customer advance, credit, return credit, applied credit.
- Recommended Consolidation Phases: Read-only customer balances and statements.
- Source Areas To Preserve First: `v_customer_advance_balance`, `CustomersRepo`, `CustomerAdvancesRepo`.

### Source code references to verify
- `database/schema.py`: `v_customer_advance_balance`, `sale_receivable_totals`
- `database/repositories/customer_advances_repo.py::get_balance`
- `database/repositories/customer_advances_repo.py::list_ledger`
- `database/repositories/customers_repo.py::get_detail_snapshot`
- `database/repositories/sales_repo.py::list_by_customer`
- `modules/customer/controller.py::_details_enrichment`
- `modules/customer/controller.py::_eligible_sales_for_application`
- `modules/sales/controller.py::_eligible_sales_for_application`

### Current behavior to preserve
Credit balance remains the signed sum exposed through `v_customer_advance_balance` and `CustomerAdvancesRepo.get_balance`. Open sales and due amounts remain whatever current repo queries return.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_customer_credit_balance(customer_id: int) -> CustomerBalance
AccountingService.get_customer_open_sales(customer_id: int) -> tuple[CustomerOpenSale, ...]
AccountingService.get_customer_receivable_summary(customer_id: int) -> CustomerReceivableSummary
```

### Original call sites to rewire
- `database/repositories/customer_advances_repo.py::get_balance`
- `database/repositories/customers_repo.py::get_detail_snapshot`
- `modules/customer/controller.py::_details_enrichment`
- `modules/customer/controller.py::_eligible_sales_for_application`
- `modules/sales/controller.py::_eligible_sales_for_application`
- `modules/sales/controller.py::_maybe_apply_customer_credit_to_sale`

### TDD plan
1. Red:
   * Add characterization tests comparing service output to `v_customer_advance_balance`, `CustomerAdvancesRepo.get_balance`, and existing open-sale queries.
   * Include customers with no credit, positive credit, applied credit, and open due.
2. Green:
   * Wrap current SQL/repo behavior in `customer_rules.py`.
   * Rewire read call sites through `AccountingService`.
3. Refactor:
   * Remove duplicated balance SQL only where tests prove parity.
   * Do not change signed credit behavior.

### Tests to add or update
- `tests/accounting/test_customer_sales_customer_balance.py::test_customer_credit_balance_matches_current_view`
- `tests/accounting/test_customer_sales_customer_balance.py::test_customer_open_sales_match_current_controller_query`
- `tests/accounting/test_customer_sales_customer_balance.py::test_customer_detail_snapshot_financial_values_are_preserved`

### Implementation steps
1. Build fixture with customer deposits, applied credit, and open sales.
2. Capture current `CustomerAdvancesRepo.get_balance` and controller open-sale values.
3. Add DTOs for customer balance, open sale, and receivable summary.
4. Implement wrappers in `customer_rules.py`.
5. Add `AccountingService` methods.
6. Rewire read call sites.
7. Leave customer advance writes untouched.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-006: Consolidate customer credit balance and open receivables

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

### Behavior-preservation checks
- Service balance equals `v_customer_advance_balance`.
- Customer detail panel values are unchanged.
- Eligible sale lists and due amounts are unchanged.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No credit application writes.

### Acceptance criteria
- [ ] Customer balance service methods exist.
- [ ] Current balance/open receivable behavior is characterized.
- [ ] Original read call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore direct repo/controller reads, remove service methods/tests/DTOs for this slice, and remove the log entry.

### Dependencies
- CS-ACC-004

### Follow-up tasks unlocked
- CS-ACC-007
- CS-ACC-013
- CS-ACC-014

## CS-ACC-007: Consolidate customer statement/history read model

### Goal
Move current customer statement/history timeline, overview, and transaction rows behind `AccountingService`.

### Why this task exists
Customer history combines sales, payments, returns, advances, applied credits, and summaries. It is scattered and user-facing, so it needs characterization before display/report rewiring.

### Source references from plan
- Accounting Areas To Consolidate: customer statements, reports, invoices, exports.
- Recommended Consolidation Phases: Read-only customer balances and statements.
- Source Areas To Preserve First: `CustomerHistoryService.full_history`, `timeline`, and customer history templates.

### Source code references to verify
- `modules/customer/history.py::sales_with_items`
- `modules/customer/history.py::sale_payments`
- `modules/customer/history.py::sale_returns`
- `modules/customer/history.py::advances_ledger`
- `modules/customer/history.py::timeline`
- `modules/customer/history.py::overview`
- `modules/customer/history.py::full_history`
- `modules/customer/controller.py::_on_history_print`
- `modules/customer/payment_history_view.py`
- `resources/templates/invoices/customer_history.html`
- `resources/templates/invoices/customer_history_table.html`

### Current behavior to preserve
Statement rows, ordering, event labels, signed amounts, summary counts, totals, and current customer history print context must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_customer_statement(
    customer_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> CustomerStatement
AccountingService.get_customer_history(customer_id: int) -> CustomerHistory
```

### Original call sites to rewire
- `modules/customer/history.py::full_history`
- `modules/customer/history.py::timeline`
- `modules/customer/history.py::overview`
- `modules/customer/controller.py::_on_history_print`
- `modules/customer/payment_history_view.py`

### TDD plan
1. Red:
   * Add characterization tests comparing `AccountingService.get_customer_statement` to `CustomerHistoryService.full_history`.
   * Include sales, receipts, refunds, return credits, deposits, and applied credits when practical.
2. Green:
   * Move/wrap the current history-building logic in `customer_rules.py`.
   * Rewire `CustomerHistoryService` to call `AccountingService`.
3. Refactor:
   * Keep templates and row keys stable.
   * Do not rename event types unless tests and current templates already use the new names.

### Tests to add or update
- `tests/accounting/test_customer_sales_customer_statement.py::test_customer_statement_matches_current_history_service`
- `tests/accounting/test_customer_sales_customer_statement.py::test_customer_statement_preserves_timeline_order_and_event_types`
- `tests/customer/test_customer_print_preview.py::test_customer_print_preview_context_unchanged`

### Implementation steps
1. Inspect current `CustomerHistoryService` row shapes.
2. Add fixture with mixed customer accounting events.
3. Add DTOs that can preserve existing row dictionaries or expose tuple rows with compatibility conversion.
4. Implement service wrapper in `customer_rules.py`.
5. Rewire `CustomerHistoryService` methods through `AccountingService`.
6. Keep print templates unchanged.
7. Document any unclear row ordering in the migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-007: Consolidate customer statement/history read model

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

### Behavior-preservation checks
- `CustomerHistoryService.full_history` returns the same keys and values.
- Printed customer history context is unchanged.
- Payment history view receives the same row shape.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No final statement format redesign.

### Acceptance criteria
- [ ] Customer statement service method exists.
- [ ] Current history behavior is characterized.
- [ ] Original history/print call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore `CustomerHistoryService` direct logic, remove service wrapper/tests/DTOs for this slice, and remove the log entry.

### Dependencies
- CS-ACC-006

### Follow-up tasks unlocked
- CS-ACC-008
- CS-ACC-010

## CS-ACC-008: Rewire sales and customer display panels

### Goal
Route current sales detail panel and customer financial panel accounting values through `AccountingService`.

### Why this task exists
Panels are user-visible but mostly read-only. Rewiring them after read models are stable proves the service can support UI display without changing behavior.

### Source references from plan
- Recommended Consolidation Phases: Display/report/template rewiring.
- Source Areas To Preserve First: Customer UI and Sales UI.
- Accounting Areas To Consolidate: customer balance, sale totals, due amount, payment status.

### Source code references to verify
- `modules/sales/controller.py::_sync_details_impl`
- `modules/sales/controller.py::_detail_payload_from_snapshot`
- `modules/sales/controller.py::_legacy_detail_snapshot`
- `modules/sales/details.py`
- `modules/customer/controller.py::_details_enrichment`
- `modules/customer/controller.py::_update_details_now`
- `modules/customer/details.py`
- `modules/sales/model.py`
- `modules/customer/model.py`

### Current behavior to preserve
Displayed values, labels, status text, button enablement inputs, and panel row shapes must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_sale_financial_summary(sale_id: int | str) -> SaleFinancialSummary
AccountingService.get_customer_receivable_summary(customer_id: int) -> CustomerReceivableSummary
AccountingService.get_customer_credit_balance(customer_id: int) -> CustomerBalance
```

### Original call sites to rewire
- `modules/sales/controller.py`
- `modules/sales/details.py` if it computes values instead of only rendering.
- `modules/customer/controller.py`
- `modules/customer/details.py` if it computes values instead of only rendering.

### TDD plan
1. Red:
   * Add focused tests that compare detail payloads before and after service route.
   * Mock or spy on `AccountingService` to prove controllers use the service.
2. Green:
   * Rewire panel data construction to service methods.
   * Keep widget rendering unchanged.
3. Refactor:
   * Remove only controller-level duplicated financial fetches that service replaces.
   * Do not change UI labels or layout.

### Tests to add or update
- `tests/accounting/test_customer_sales_display_rewiring.py::test_sales_detail_payload_routes_through_accounting_service`
- `tests/accounting/test_customer_sales_display_rewiring.py::test_customer_detail_financial_payload_routes_through_accounting_service`
- `tests/sales/test_sale_details_return_credit.py::test_sale_details_financial_values_unchanged`

### Implementation steps
1. Identify exact payload fields used by sales/customer detail widgets.
2. Add characterization tests for those payloads.
3. Inject or construct `AccountingService` following Vendor + Purchase controller patterns.
4. Rewire controller financial data calls.
5. Keep widget methods and UI text unchanged.
6. Update migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-008: Rewire sales and customer display panels

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

### Behavior-preservation checks
- Detail payload snapshots match prior behavior.
- Button enablement conditions are unchanged.
- No UI text or layout changes.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No report or invoice rewiring.

### Acceptance criteria
- [ ] Sales detail panel financial reads use `AccountingService`.
- [ ] Customer financial panel reads use `AccountingService`.
- [ ] Existing visible values are preserved by tests.
- [ ] Migration log entry is appended.

### Rollback notes
Restore controller read paths to repositories, remove display-rewiring tests/log entry.

### Dependencies
- CS-ACC-004
- CS-ACC-006
- CS-ACC-007

### Follow-up tasks unlocked
- CS-ACC-009
- CS-ACC-010

## CS-ACC-009: Consolidate sale invoice and quotation financial sourcing

### Goal
Move current sale invoice and quotation invoice financial context behind `AccountingService`, then rewire invoice generation to use that context.

### Why this task exists
Invoice totals can diverge from UI/report totals. This card preserves the current invoice behavior while moving its financial sourcing to the central service.

### Source references from plan
- Recommended Consolidation Phases: Display/report/template rewiring and quotation behavior.
- Source Areas To Preserve First: invoice templates and `modules/sales/controller.py`.
- Manual Review Before Task Cards: invoice totals in `modules/sales/controller.py` may not match UI/report values.

### Source code references to verify
- `modules/sales/controller.py::_generate_invoice_html_content`
- `modules/sales/controller.py::_generate_quotation_html_content`
- `modules/sales/controller.py::_print_sale_invoice`
- `modules/sales/controller.py::_print_quotation_invoice`
- `resources/templates/invoices/sale_invoice.html`
- `resources/templates/invoices/quotation_invoice.html`
- `widgets/invoice_preview.py`
- `database/repositories/company_info_repo.py::invoice_context`

### Current behavior to preserve
Invoice HTML context, displayed totals, paid amount, due amount, return credit, applied credit, payment rows, and quotation totals must render the same values as current controller-generated output.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_sale_invoice_financials(sale_id: int | str) -> SaleInvoiceFinancials
AccountingService.get_quotation_financials(quotation_id: int | str) -> QuotationFinancials
```

### Original call sites to rewire
- `modules/sales/controller.py::_generate_invoice_html_content`
- `modules/sales/controller.py::_generate_quotation_html_content`
- `modules/sales/controller.py::_print_sale_invoice`
- `modules/sales/controller.py::_print_quotation_invoice`
- `widgets/invoice_preview.py` only if sale invoice preview support is added through existing patterns.

### TDD plan
1. Red:
   * Add characterization tests for generated sale invoice context/HTML financial values.
   * Add characterization tests for quotation invoice financial values.
2. Green:
   * Wrap current controller financial context building in `sales_rules.py`.
   * Rewire controller generation methods to `AccountingService`.
3. Refactor:
   * Remove duplicated invoice financial queries only after output parity is tested.
   * Keep templates unchanged unless a key must be passed from the service to preserve output.

### Tests to add or update
- `tests/accounting/test_customer_sales_invoice_financials.py::test_sale_invoice_financials_match_current_controller_context`
- `tests/accounting/test_customer_sales_invoice_financials.py::test_quotation_invoice_financials_match_current_controller_context`
- `tests/customer/test_customer_print_preview.py` only if customer history template context is affected.

### Implementation steps
1. Capture current invoice context keys and rendered money values.
2. Add `SaleInvoiceFinancials` and `QuotationFinancials` DTOs that can carry compatibility context.
3. Implement service current-rule functions.
4. Rewire sales controller invoice generation.
5. Keep template files unchanged unless tests require a compatibility key.
6. Document any known invoice/report mismatch in the migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-009: Consolidate sale invoice and quotation financial sourcing

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

### Behavior-preservation checks
- Rendered invoice financial values match pre-migration output.
- Template context keys used by templates are unchanged.
- Sale invoice and quotation invoice still print/export from the same controller paths.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No template redesign.

### Acceptance criteria
- [ ] Invoice financial service methods exist.
- [ ] Sale and quotation invoice outputs are characterized.
- [ ] Invoice generation routes through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore controller invoice financial queries, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-003
- CS-ACC-004
- CS-ACC-005

### Follow-up tasks unlocked
- CS-ACC-019

## CS-ACC-010: Consolidate sales, customer, dashboard, and export financial reads

### Goal
Move current sales report, customer aging/report, dashboard KPI, and export financial read values behind `AccountingService`.

### Why this task exists
Reports and dashboards read sale receivables, collections, returns, profit, and payment activity through scattered SQL. Rewiring these after core read models avoids report-specific accounting drift.

### Source references from plan
- Recommended Consolidation Phases: Display/report/template rewiring.
- Source Areas To Preserve First: `modules/reporting/*`, `modules/dashboard/*`.
- Accounting Areas To Consolidate: reports, dashboards, statements, exports.

### Source code references to verify
- `modules/reporting/customer_aging_reports.py`
- `modules/reporting/sales_reports.py`
- `modules/reporting/payment_reports.py`
- `modules/reporting/enhanced_payment_reports.py`
- `modules/reporting/comprehensive_payments_reports.py`
- `modules/reporting/financial_reports.py`
- `modules/reporting/csv_export.py`
- `modules/reporting/html_export.py`
- `database/repositories/reporting_repo.py`
- `database/repositories/dashboard_repo.py`
- `modules/dashboard/controller.py`
- `modules/dashboard/financial_overview_widget.py`
- `modules/dashboard/payment_summary_widget.py`

### Current behavior to preserve
Report rows, dashboard totals, filters, date cutoff behavior, CSV/HTML export row shapes, AR aging buckets, sales return summaries, and payment report totals must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/reports/ar_ap_summary.py`
- `modules/accounting/reports/party_ledger.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_ar_summary(cutoff_date: str | None = None) -> ARSummary
AccountingService.get_customer_aging(cutoff_date: str) -> CustomerAgingReport
AccountingService.get_sales_report(start_date: str | None = None, end_date: str | None = None) -> SalesReportBundle
AccountingService.get_customer_report(customer_id: int | None = None) -> CustomerReportBundle
AccountingService.get_sales_dashboard_metrics(start_date: str | None = None, end_date: str | None = None) -> SalesDashboardMetrics
```

### Original call sites to rewire
- `modules/reporting/customer_aging_reports.py`
- `modules/reporting/sales_reports.py`
- `modules/reporting/payment_reports.py`
- `modules/reporting/financial_reports.py`
- `modules/reporting/csv_export.py` if it performs financial shaping.
- `modules/reporting/html_export.py` if it performs financial shaping.
- `database/repositories/dashboard_repo.py` read methods for sales/accounting KPIs.
- `modules/dashboard/controller.py`

### TDD plan
1. Red:
   * Add characterization tests comparing service report rows to existing report/repository outputs.
   * Include cutoff behavior for customer aging and historical status.
2. Green:
   * Wrap current report SQL in accounting report/current-rule modules.
   * Rewire report/dashboard call sites to `AccountingService`.
3. Refactor:
   * Keep report row keys and export field names stable.
   * Do not merge unrelated report queries.

### Tests to add or update
- `tests/accounting/test_customer_sales_reports.py::test_customer_aging_matches_current_report`
- `tests/accounting/test_customer_sales_reports.py::test_sales_report_financial_rows_match_current_report`
- `tests/accounting/test_customer_sales_reports.py::test_dashboard_sales_metrics_match_current_repo`
- Existing `tests/reporting/test_customer_aging_cutoff.py`
- Existing `tests/reporting/test_sales_reports_historical_status.py`

### Implementation steps
1. Identify exact row shapes used by report tabs and exports.
2. Add service DTOs or compatibility bundles that preserve dict row shapes.
3. Wrap current `ReportingRepo`/dashboard SQL behavior.
4. Add `AccountingService` report methods.
5. Rewire report/dashboard modules through the service.
6. Keep export formatting unchanged.
7. Document any cutoff/status ambiguity in the migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-010: Consolidate sales, customer, dashboard, and export financial reads

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

### Behavior-preservation checks
- Report row counts and money totals match existing outputs.
- Dashboard KPI values match existing repository outputs.
- CSV/HTML exports keep the same headers and values.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No broad report redesign.

### Acceptance criteria
- [ ] Report/dashboard service methods exist.
- [ ] Current report/dashboard behavior is characterized.
- [ ] Report/dashboard call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore report/dashboard modules to direct repositories, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-004
- CS-ACC-005
- CS-ACC-006
- CS-ACC-007

### Follow-up tasks unlocked
- CS-ACC-017
- CS-ACC-018

## CS-ACC-011: Consolidate customer payment history read model

### Goal
Move current customer and sale payment history reads behind `AccountingService`.

### Why this task exists
Payment history is used by sale details, customer history, payment tabs, invoices, and payment reports. It should be centralized before payment write behavior moves.

### Source references from plan
- Accounting Areas To Consolidate: sale payment, clearing, overpayment, payment methods.
- Recommended Consolidation Phases: Customer payment current behavior.
- Source Areas To Preserve First: `SalePaymentsRepo` and customer UI.

### Source code references to verify
- `database/repositories/sale_payments_repo.py::list_by_sale`
- `database/repositories/sale_payments_repo.py::list_by_customer`
- `database/repositories/sale_payments_repo.py::get_latest_payment_for_sale`
- `modules/sales/controller.py::_sync_payment_tab_history`
- `modules/sales/controller.py::_legacy_detail_snapshot`
- `modules/sales/controller.py::_generate_invoice_html_content`
- `modules/customer/history.py::sale_payments`
- `modules/customer/payment_history_view.py`
- `modules/reporting/payment_reports.py`

### Current behavior to preserve
Payment row order, clearing state values, method metadata, refund rows, overpayment converted amounts, and latest-payment selection must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_sale_payment_history(sale_id: int | str) -> tuple[SalePaymentRow, ...]
AccountingService.get_customer_payment_history(customer_id: int) -> tuple[SalePaymentRow, ...]
AccountingService.get_latest_sale_payment(sale_id: int | str) -> SalePaymentRow | None
```

### Original call sites to rewire
- `database/repositories/sale_payments_repo.py::list_by_sale`
- `database/repositories/sale_payments_repo.py::list_by_customer`
- `database/repositories/sale_payments_repo.py::get_latest_payment_for_sale`
- `modules/sales/controller.py`
- `modules/customer/history.py`
- `modules/customer/payment_history_view.py`
- `modules/reporting/payment_reports.py`

### TDD plan
1. Red:
   * Add characterization tests comparing service payment history to `SalePaymentsRepo` methods.
   * Include receipt, refund, pending/cleared/bounced, and overpayment fields if fixtures allow.
2. Green:
   * Wrap current payment history queries in accounting current rules.
   * Rewire read call sites through `AccountingService`.
3. Refactor:
   * Keep row shape compatibility for UI/report code.
   * Do not change clearing semantics.

### Tests to add or update
- `tests/accounting/test_customer_sales_payment_history.py::test_sale_payment_history_matches_repo`
- `tests/accounting/test_customer_sales_payment_history.py::test_customer_payment_history_matches_repo`
- `tests/accounting/test_customer_sales_payment_history.py::test_latest_sale_payment_matches_repo`

### Implementation steps
1. Capture current `SalePaymentsRepo` row fields.
2. Add `SalePaymentRow` DTO if not already present.
3. Implement current-rule history functions.
4. Add `AccountingService` methods.
5. Rewire repo compatibility methods and UI/report readers.
6. Keep payment write methods untouched.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-011: Consolidate customer payment history read model

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

### Behavior-preservation checks
- Service rows equal current repo rows.
- UI payment history displays same values.
- Invoice payment detail context is unchanged.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No payment writes.

### Acceptance criteria
- [ ] Payment history service methods exist.
- [ ] Current payment history behavior is characterized.
- [ ] Original read call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore direct `SalePaymentsRepo` reads, remove service wrappers/tests/log entry.

### Dependencies
- CS-ACC-004
- CS-ACC-005

### Follow-up tasks unlocked
- CS-ACC-012
- CS-ACC-016
- CS-ACC-017

## CS-ACC-012: Consolidate customer payment write and clearing behavior

### Goal
Move current customer receipt write behavior, clearing state updates, clearing reopen behavior, and overpayment-to-credit behavior behind `AccountingService`.

### Why this task exists
Customer payment writes affect sale paid amount, payment status, customer credit, bank movement, reports, and invoices. This is the first high-risk write-side slice, so it depends on read-side characterization.

### Source references from plan
- Accounting Areas To Consolidate: sale payment, clearing, overpayment, cash/bank movement.
- Recommended Consolidation Phases: Customer payment current behavior.
- Manual Review Before Task Cards: overpayment-to-credit behavior and posted/cleared differences.

### Source code references to verify
- `database/repositories/sale_payments_repo.py::record_payment_with_conn`
- `database/repositories/sale_payments_repo.py::record_payment`
- `database/repositories/sale_payments_repo.py::update_clearing_state`
- `database/repositories/sale_payments_repo.py::reopen_clearing_state`
- `database/repositories/sale_payments_repo.py::_grant_customer_credit`
- `modules/sales/controller.py::_record_payment`
- `modules/sales/controller.py::_on_payment_status_change_requested`
- `modules/sales/payment_form.py`
- `modules/customer/actions.py`
- `modules/customer/receipt_dialog.py`
- `database/schema.py`: `sale_payments`, payment triggers, method checks.

### Current behavior to preserve
Payment insert, refund insert where current payment paths use it, clearing defaults, clearing-state reopen authorization, overpayment conversion to customer credit, converted amount fields, and sale header rollups must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/dto.py`
- `modules/accounting/validators.py`

### Proposed AccountingService API
```python
AccountingService.preview_customer_payment_effect(payload: CustomerPaymentPayload) -> CustomerPaymentEffect
AccountingService.record_customer_payment_event(payload: CustomerPaymentPayload) -> CustomerPaymentResult
AccountingService.update_customer_payment_state(
    payment_id: int,
    *,
    clearing_state: str,
    cleared_date: str | None = None,
    notes: str | None = None,
) -> int
AccountingService.reopen_customer_payment_state(payment_id: int, *, reason: str | None = None) -> int
```

### Original call sites to rewire
- `database/repositories/sale_payments_repo.py::record_payment`
- `database/repositories/sale_payments_repo.py::record_payment_with_conn`
- `database/repositories/sale_payments_repo.py::update_clearing_state`
- `database/repositories/sale_payments_repo.py::reopen_clearing_state`
- `modules/sales/controller.py::_record_payment`
- `modules/sales/controller.py::_on_payment_status_change_requested`
- `modules/customer/actions.py` receipt path.

### TDD plan
1. Red:
   * Add characterization tests for recording customer payments through repo and service.
   * Include exact overpayment-to-credit behavior.
   * Include clearing state update and reopen behavior.
2. Green:
   * Move/wrap current write logic in `customer_rules.py` or `sales_rules.py`.
   * Rewire repository and controller call sites through `AccountingService`.
3. Refactor:
   * Keep DB triggers as integrity layer.
   * Remove duplicate write logic only after service tests and repo compatibility tests pass.

### Tests to add or update
- `tests/accounting/test_customer_sales_payment_event.py::test_record_customer_payment_preserves_sale_payment_row`
- `tests/accounting/test_customer_sales_payment_event.py::test_customer_payment_overpayment_to_credit_is_preserved`
- `tests/accounting/test_customer_sales_payment_event.py::test_update_customer_payment_state_preserves_reopen_lifecycle`
- Existing `tests/verification_tests/test_sale_payment_overpayment_credit.py`
- Existing `tests/sales/test_payment_methods_integration.py`

### Implementation steps
1. Capture current payment payload shape from forms/controllers.
2. Add payment payload/result/effect DTOs.
3. Move current write behavior into accounting current rules with connection reuse.
4. Add service methods.
5. Rewire `SalePaymentsRepo` methods as compatibility wrappers around the service.
6. Rewire sales/customer controller write paths.
7. Verify overpayment credit rows are identical.
8. Update migration log with any unclear clearing behavior.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-012: Consolidate customer payment write and clearing behavior

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

### Behavior-preservation checks
- Inserted `sale_payments` rows match current behavior.
- Overpayment creates the same `customer_advances` row and flags.
- Header payment status and paid amount are unchanged.
- Clearing reopen lifecycle behaves the same.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No new payment methods.

### Acceptance criteria
- [ ] Customer payment write service methods exist.
- [ ] Current payment write and clearing behavior is characterized.
- [ ] Original write call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore `SalePaymentsRepo` write logic and controller calls, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-005
- CS-ACC-011

### Follow-up tasks unlocked
- CS-ACC-013
- CS-ACC-016
- CS-ACC-017

## CS-ACC-013: Consolidate customer advance and credit grant behavior

### Goal
Move current customer deposit, customer credit grant, return-credit row creation, credit ledger read, and credit balance write-side helpers behind `AccountingService`.

### Why this task exists
Customer credit is stored as signed `customer_advances` rows and is used by payments, returns, customer panels, and statements. This card centralizes credit grant behavior before credit application.

### Source references from plan
- Accounting Areas To Consolidate: customer advance, credit, return credit, applied credit.
- Recommended Consolidation Phases: Customer credit/advance current behavior.
- Source Areas To Preserve First: `CustomerAdvancesRepo`.

### Source code references to verify
- `database/repositories/customer_advances_repo.py::grant_credit`
- `database/repositories/customer_advances_repo.py::add_return_credit`
- `database/repositories/customer_advances_repo.py::add_deposit`
- `database/repositories/customer_advances_repo.py::list_ledger`
- `modules/customer/controller.py::_on_record_advance`
- `modules/customer/actions.py::record_customer_advance`
- `modules/customer/receipt_dialog.py`
- `modules/customer/history.py::advances_ledger`
- `database/schema.py`: `customer_advances`, metadata columns and triggers.

### Current behavior to preserve
Positive customer credit/deposit/return-credit rows, source types, notes, dates, payment metadata, and current balance effects remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/dto.py`
- `modules/accounting/validators.py`

### Proposed AccountingService API
```python
AccountingService.record_customer_credit_event(payload: CustomerCreditPayload) -> CustomerCreditResult
AccountingService.get_customer_credit_ledger(customer_id: int) -> tuple[CustomerCreditLedgerRow, ...]
AccountingService.validate_customer_payment_metadata(metadata: CustomerPaymentMetadata) -> None
```

### Original call sites to rewire
- `database/repositories/customer_advances_repo.py::grant_credit`
- `database/repositories/customer_advances_repo.py::add_return_credit`
- `database/repositories/customer_advances_repo.py::add_deposit`
- `database/repositories/customer_advances_repo.py::list_ledger`
- `modules/customer/controller.py::_on_record_advance`
- `modules/customer/actions.py`
- `modules/customer/history.py::advances_ledger`

### TDD plan
1. Red:
   * Add characterization tests for deposit, manual credit, return credit, payment metadata, and ledger rows.
   * Compare service behavior to `CustomerAdvancesRepo`.
2. Green:
   * Wrap current credit grant behavior in `customer_rules.py`.
   * Rewire repo/controller/action call sites.
3. Refactor:
   * Keep schema constraints as final validation.
   * Do not change signed amount semantics.

### Tests to add or update
- `tests/accounting/test_customer_sales_customer_credit_event.py::test_customer_deposit_event_matches_repo`
- `tests/accounting/test_customer_sales_customer_credit_event.py::test_customer_return_credit_event_matches_repo`
- `tests/accounting/test_customer_sales_customer_credit_event.py::test_customer_credit_ledger_matches_repo`

### Implementation steps
1. Inspect current `CustomerAdvancesRepo` source type and metadata behavior.
2. Add payload/result/ledger DTOs.
3. Implement current-rule functions.
4. Add service methods and metadata validation if needed.
5. Rewire repository compatibility methods.
6. Rewire controller/action grant paths.
7. Leave credit application for CS-ACC-014.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-013: Consolidate customer advance and credit grant behavior

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

### Behavior-preservation checks
- `customer_advances` rows match current inserts.
- Credit balance effects match current view.
- Customer history ledger rows are unchanged.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No credit application behavior.

### Acceptance criteria
- [ ] Credit grant service methods exist.
- [ ] Current credit/deposit behavior is characterized.
- [ ] Original grant/ledger call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore `CustomerAdvancesRepo` grant/ledger logic, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-006
- CS-ACC-012

### Follow-up tasks unlocked
- CS-ACC-014
- CS-ACC-015
- CS-ACC-017

## CS-ACC-014: Consolidate customer credit application behavior

### Goal
Move current applying of customer credit/advance to sales behind `AccountingService`.

### Why this task exists
Credit application changes customer credit balance, sale outstanding, sale status, statements, and reports. It must follow customer balance and sale outstanding read-side cards.

### Source references from plan
- Accounting Areas To Consolidate: applied credit, customer advance, credit application.
- Recommended Consolidation Phases: Customer credit/advance current behavior.
- Manual Review Before Task Cards: posted/cleared differences and credit application behavior.

### Source code references to verify
- `database/repositories/customer_advances_repo.py::apply_credit_to_sale`
- `database/repositories/customer_advances_repo.py::apply_to_sale`
- `database/repositories/customer_advances_repo.py::_clamp_non_negative`
- `modules/customer/controller.py::_on_apply_advance`
- `modules/customer/actions.py::apply_customer_advance`
- `modules/sales/controller.py::_maybe_apply_customer_credit_to_sale`
- `modules/sales/controller.py::_on_apply_credit`
- `database/schema.py`: `trg_advances_no_overdraw`, `trg_customer_advances_not_exceed_remaining_due`, `trg_adv_applied_from_customer_*`

### Current behavior to preserve
Negative `customer_advances` application rows, due cap behavior, overdraw prevention, source type, source id, sale header rollup updates, and current UI prevalidation remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/dto.py`
- `modules/accounting/validators.py`

### Proposed AccountingService API
```python
AccountingService.preview_customer_credit_allocation(customer_id: int, amount: Decimal) -> CustomerCreditAllocation
AccountingService.validate_customer_credit_application(payload: CustomerCreditApplicationPayload) -> None
AccountingService.record_customer_credit_application_event(payload: CustomerCreditApplicationPayload) -> CustomerCreditApplicationResult
```

### Original call sites to rewire
- `database/repositories/customer_advances_repo.py::apply_credit_to_sale`
- `database/repositories/customer_advances_repo.py::apply_to_sale`
- `modules/customer/controller.py::_on_apply_advance`
- `modules/customer/actions.py::apply_customer_advance`
- `modules/sales/controller.py::_maybe_apply_customer_credit_to_sale`
- `modules/sales/controller.py::_on_apply_credit`

### TDD plan
1. Red:
   * Add characterization tests for applying valid credit, applying more than available, applying more than sale due, and sale status effects.
   * Compare service behavior to current repo behavior.
2. Green:
   * Wrap current application write behavior in `customer_rules.py`.
   * Rewire repo/controller/action call sites.
3. Refactor:
   * Keep DB triggers and validation messages unless tests prove exact replacement.
   * Do not change FIFO/allocation behavior unless current UI already does it.

### Tests to add or update
- `tests/accounting/test_customer_sales_credit_application.py::test_customer_credit_application_matches_repo`
- `tests/accounting/test_customer_sales_credit_application.py::test_customer_credit_application_preserves_due_cap`
- `tests/accounting/test_customer_sales_credit_application.py::test_customer_credit_application_updates_sale_status_as_before`
- Existing `tests/sales/test_sales_apply_customer_credit.py`

### Implementation steps
1. Capture current application payload shape from customer and sales controllers.
2. Add application payload/result DTOs.
3. Implement validation wrapper that preserves current exceptions/messages where asserted.
4. Implement record function using current repo SQL behavior.
5. Add `AccountingService` methods.
6. Rewire repository and controller call sites.
7. Document unclear allocation assumptions in the migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-014: Consolidate customer credit application behavior

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

### Behavior-preservation checks
- Inserted applied-credit rows match current behavior.
- Sale outstanding/status after application match current behavior.
- Existing controller validation and messages remain unchanged where tested.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No auto-allocation redesign.

### Acceptance criteria
- [ ] Credit application service methods exist.
- [ ] Current application behavior is characterized.
- [ ] Original write call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore `CustomerAdvancesRepo` application logic and controller calls, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-004
- CS-ACC-006
- CS-ACC-013

### Follow-up tasks unlocked
- CS-ACC-015
- CS-ACC-020

## CS-ACC-015: Consolidate sale return financial behavior

### Goal
Move current sale return financial preview, return value calculation, settlement between cash refund and customer credit, and receivable effects behind `AccountingService`.

### Why this task exists
Sale returns touch receivables, customer credits, refunds, COGS reversal, inventory restoration, invoices, reports, and profit. This card consolidates financial behavior while leaving inventory side effects for the dependent inventory card unless inseparable.

### Source references from plan
- Accounting Areas To Consolidate: sale returns, cash refund, customer credit, COGS reversal, inventory restoration.
- Recommended Consolidation Phases: Sale return/refund current behavior.
- Manual Review Before Task Cards: return settlement math in `SalesRepo.record_return`.

### Source code references to verify
- `database/repositories/sales_repo.py::record_return`
- `database/repositories/sales_repo.py::sale_return_totals`
- `database/repositories/sales_repo.py::get_receivable_position`
- `modules/sales/return_form.py`
- `modules/sales/controller.py::_return`
- `modules/sales/controller.py::_handle_return_dialog_accept`
- `database/schema.py`: `sale_return_snapshots`, return triggers.
- `database/repositories/customer_advances_repo.py::add_return_credit`
- `database/repositories/sale_payments_repo.py::record_payment`

### Current behavior to preserve
Return value, order-discount proration, cash refund amount, customer return-credit amount, notes, transaction linkage, sale receivable impact, and current settlement math must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/inventory_rules.py` only for inseparable return inventory writes.
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.preview_sale_return_effect(payload: SaleReturnPreviewPayload) -> SaleReturnEffect
AccountingService.get_sale_return_values(sale_id: int | str) -> tuple[SaleReturnValue, ...]
AccountingService.get_sale_return_totals(sale_id: int | str) -> SaleReturnTotals
AccountingService.record_sale_return_event(payload: SaleReturnPayload) -> SaleReturnResult
```

### Original call sites to rewire
- `database/repositories/sales_repo.py::record_return`
- `database/repositories/sales_repo.py::sale_return_totals`
- `modules/sales/return_form.py`
- `modules/sales/controller.py::_return`
- `modules/sales/controller.py::_handle_return_dialog_accept`

### TDD plan
1. Red:
   * Add characterization tests for return preview and recorded return settlement.
   * Include return credit only, refund now, partial refund/credit split, and full return if existing tests cover it.
2. Green:
   * Wrap current return financial behavior in `sales_rules.py`.
   * Rewire return form/controller/repository call sites through `AccountingService`.
3. Refactor:
   * Keep snapshot triggers intact.
   * Do not alter settlement math or return valuation.

### Tests to add or update
- `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_preview_preserves_current_value`
- `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_credit_settlement_matches_current_repo`
- `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_refund_settlement_matches_current_repo`
- Existing `tests/sales/test_sale_return_receivables.py`
- Existing `tests/verification_tests/test_sale_return_settlement_atomicity.py`

### Implementation steps
1. Inspect `SalesRepo.record_return` settlement and snapshot dependencies.
2. Add return payload/result/effect DTOs.
3. Write service characterization tests against current repo behavior.
4. Implement current-rule wrappers.
5. Add `AccountingService` methods.
6. Rewire repository/controller/form call sites.
7. Keep inventory transaction writing unchanged if it cannot be separated safely; document coupling in migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-015: Consolidate sale return financial behavior

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

### Behavior-preservation checks
- Return value and settlement rows match current behavior.
- Receivable position after return is unchanged.
- Existing sale return tests pass.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No profit/COGS correction.

### Acceptance criteria
- [ ] Sale return service methods exist.
- [ ] Current return financial behavior is characterized.
- [ ] Original return call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore `SalesRepo.record_return` direct behavior and controller/form calls, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-004
- CS-ACC-005
- CS-ACC-013
- CS-ACC-014

### Follow-up tasks unlocked
- CS-ACC-016
- CS-ACC-018

## CS-ACC-016: Consolidate customer refund behavior

### Goal
Move current customer refund read/write behavior behind `AccountingService`, including refunds recorded through sale payment rows and refunds caused by sale returns.

### Why this task exists
Refunds are represented in payment/history/report flows and can overlap with sale returns. Separating refund behavior keeps payment and return settlement logic understandable before bank/cash consolidation.

### Source references from plan
- Accounting Areas To Consolidate: customer refund, sale payment receipts/refunds, return refund.
- Recommended Consolidation Phases: Sale return/refund current behavior.
- Source Areas To Preserve First: `SalePaymentsRepo`, customer history, reports.

### Source code references to verify
- `database/repositories/sale_payments_repo.py::record_payment`
- `database/repositories/sale_payments_repo.py::list_by_customer`
- `database/repositories/sales_repo.py::apply_refund`
- `database/repositories/sales_repo.py::record_return`
- `modules/customer/history.py::sale_payments`
- `modules/customer/history.py::timeline`
- `modules/sales/controller.py::_handle_return_dialog_accept`
- `modules/reporting/payment_reports.py`
- `tests/customer/test_customer_history_refunds.py`

### Current behavior to preserve
Refund rows, negative/positive sign conventions, clearing state, customer history event labels, sale return refund linkage, and payment report treatment must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.record_customer_refund_event(payload: CustomerRefundPayload) -> CustomerRefundResult
AccountingService.get_customer_refunds(customer_id: int) -> tuple[CustomerRefundRow, ...]
AccountingService.get_sale_refunds(sale_id: int | str) -> tuple[CustomerRefundRow, ...]
```

### Original call sites to rewire
- `database/repositories/sales_repo.py::apply_refund`
- Refund branch inside `database/repositories/sales_repo.py::record_return`
- Refund branch inside `database/repositories/sale_payments_repo.py::record_payment` if it owns refund insertion.
- `modules/customer/history.py`
- `modules/reporting/payment_reports.py`

### TDD plan
1. Red:
   * Add characterization tests for direct refund rows and sale-return refund rows.
   * Compare customer history and payment report output.
2. Green:
   * Wrap current refund behavior in accounting current rules.
   * Rewire refund call sites through `AccountingService`.
3. Refactor:
   * Keep sign conventions and event labels stable.
   * Do not merge refund behavior with final ledger concepts.

### Tests to add or update
- `tests/accounting/test_customer_sales_customer_refunds.py::test_customer_refund_event_matches_current_payment_row`
- `tests/accounting/test_customer_sales_customer_refunds.py::test_sale_return_refund_history_matches_current_behavior`
- Existing `tests/customer/test_customer_history_refunds.py`

### Implementation steps
1. Identify current refund representation in `sale_payments`.
2. Add refund payload/result/row DTOs.
3. Implement current-rule refund read/write helpers.
4. Add `AccountingService` methods.
5. Rewire refund call sites.
6. Keep sale return financial settlement behavior from CS-ACC-015 intact.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-016: Consolidate customer refund behavior

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

### Behavior-preservation checks
- Refund rows and signs match current DB rows.
- Customer history refund labels and amounts are unchanged.
- Payment reports still total refunds the same way.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No refund workflow redesign.

### Acceptance criteria
- [ ] Refund service methods exist.
- [ ] Current refund behavior is characterized.
- [ ] Original refund call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore refund logic to original repository paths, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-011
- CS-ACC-012
- CS-ACC-015

### Follow-up tasks unlocked
- CS-ACC-017

## CS-ACC-017: Consolidate bank/cash movements from customer and sales flows

### Goal
Move current bank/cash movement reads and validation for customer receipts, refunds, advances, and sale-return settlements behind `AccountingService`.

### Why this task exists
Customer/Sales money movement appears in payment forms, payment repos, customer advance metadata, bank ledger views, dashboards, and reports. This card centralizes the sales-side cash/bank read model after write behaviors are stable.

### Source references from plan
- Accounting Areas To Consolidate: payment methods, cash/bank movement, reports and dashboards.
- Recommended Consolidation Phases: Customer payment current behavior and reports.
- Source Areas To Preserve First: bank ledger views, payment metadata, reports.

### Source code references to verify
- `database/schema.py`: `v_bank_ledger`, `v_bank_ledger_ext`, sale payment method triggers.
- `database/repositories/sale_payments_repo.py::_normalize_and_validate`
- `database/repositories/customer_advances_repo.py`
- `database/repositories/dashboard_repo.py`
- `modules/sales/payment_form.py`
- `modules/customer/receipt_dialog.py`
- `modules/reporting/payment_reports.py`
- `modules/reporting/comprehensive_payments_reports.py`
- `modules/accounting/current_rules/bank_rules.py`

### Current behavior to preserve
Payment method requirements, active bank account checks, cash/bank ledger rows, bank labels, clearing dates, and report/dashboard money movement totals remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/validators.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.validate_customer_payment_metadata(metadata: CustomerPaymentMetadata) -> None
AccountingService.get_customer_cash_movements(start_date: str | None = None, end_date: str | None = None) -> tuple[CustomerCashMovement, ...]
AccountingService.get_bank_ledger(start_date: str | None = None, end_date: str | None = None, account_id: int | None = None) -> tuple[BankLedgerRow, ...]
```

### Original call sites to rewire
- `database/repositories/sale_payments_repo.py::_normalize_and_validate`
- `database/repositories/customer_advances_repo.py` payment metadata validation.
- `modules/sales/payment_form.py` only for service-backed validation if it currently duplicates accounting checks.
- `modules/customer/receipt_dialog.py` only for service-backed validation if it currently duplicates accounting checks.
- `modules/reporting/payment_reports.py`
- `database/repositories/dashboard_repo.py` bank movement reads.

### TDD plan
1. Red:
   * Add characterization tests for payment metadata validation and bank ledger rows from customer flows.
   * Include cash, bank, cheque/check, card if currently supported.
2. Green:
   * Wrap current validation/read SQL in bank/customer current rules.
   * Rewire repos/reports/dashboard to service methods.
3. Refactor:
   * Keep DB triggers as final integrity checks.
   * Do not add new payment methods.

### Tests to add or update
- `tests/accounting/test_customer_sales_cash_movements.py::test_customer_cash_movements_match_bank_ledger_view`
- `tests/accounting/test_customer_sales_cash_movements.py::test_customer_payment_metadata_validation_matches_repo`
- `tests/accounting/test_customer_sales_cash_movements.py::test_customer_advance_payment_metadata_validation_matches_repo`

### Implementation steps
1. Inventory current customer/sale bank metadata fields.
2. Add customer payment metadata and cash movement DTOs.
3. Implement validators using current repo/schema behavior.
4. Extend `bank_rules.py` for customer cash movement reads.
5. Add service methods.
6. Rewire repo/report/dashboard reads and validation points.
7. Record any unclear method rules in the migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-017: Consolidate bank/cash movements from customer and sales flows

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

### Behavior-preservation checks
- `v_bank_ledger`/`v_bank_ledger_ext` customer-side rows match service rows.
- Existing validation accepts and rejects the same payloads.
- Dashboard/payment report totals are unchanged.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No new bank account workflow.

### Acceptance criteria
- [ ] Customer cash movement service methods exist.
- [ ] Current bank/cash behavior is characterized.
- [ ] Original validation/read call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore direct repo/report/dashboard bank queries and validators, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-012
- CS-ACC-013
- CS-ACC-016

### Follow-up tasks unlocked
- CS-ACC-020

## CS-ACC-018: Consolidate sale inventory, COGS, margin, and profit effects

### Goal
Move current sale inventory event writes, sale return inventory restoration, returnable quantity reads, COGS reads, margin reads, and profit/loss financial effects behind `AccountingService`.

### Why this task exists
Sales affect stock, cost, return snapshots, COGS reversal, profit, dashboard metrics, and sales reports. This high-risk slice should follow sale totals, returns, and reports.

### Source references from plan
- Accounting Areas To Consolidate: inventory, stock decrement, stock restoration, COGS, margin/profit.
- Recommended Consolidation Phases: Inventory/COGS/profit side effects.
- Manual Review Before Task Cards: average-cost view and FIFO view both exist.

### Source code references to verify
- `database/repositories/sales_repo.py::_insert_inventory_sale`
- `database/repositories/sales_repo.py::_check_stock_availability`
- `database/repositories/sales_repo.py::record_return`
- `database/schema.py`: `inventory_transactions`, `sale_item_cogs`, `sale_item_fifo_cogs`, `sale_financial_events`, `profit_loss_view`, sale return snapshot triggers.
- `database/repositories/inventory_repo.py`
- `database/repositories/reporting_repo.py`
- `database/repositories/dashboard_repo.py`
- `modules/reporting/sales_reports.py`
- `modules/inventory/`
- `tests/sales/test_sale_return_receivables.py`
- `tests/verification_tests/test_sale_stock_validation.py`

### Current behavior to preserve
Stock decrement, stock validation, sale return stock restoration, COGS source selection, return snapshot COGS reversal, margin/profit calculations, and report/dashboard outputs remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/reports/party_ledger.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.record_sale_inventory_event(payload: SaleInventoryPayload) -> SaleInventoryResult
AccountingService.record_sale_return_inventory_event(payload: SaleReturnInventoryPayload) -> SaleReturnInventoryResult
AccountingService.get_sale_returnable_quantities(sale_id: int | str) -> dict[int, Decimal]
AccountingService.get_sale_cogs(sale_id: int | str) -> SaleCogsSummary
AccountingService.get_sales_profit_summary(start_date: str | None = None, end_date: str | None = None) -> SalesProfitSummary
```

### Original call sites to rewire
- `database/repositories/sales_repo.py::_insert_inventory_sale`
- `database/repositories/sales_repo.py::_check_stock_availability` only if it owns accounting inventory availability logic.
- `database/repositories/sales_repo.py::record_return`
- `database/repositories/reporting_repo.py` sales COGS/profit reads.
- `database/repositories/dashboard_repo.py` profit and inventory-impact reads.
- `modules/reporting/sales_reports.py`

### TDD plan
1. Red:
   * Add characterization tests for sale inventory rows, sale return inventory rows, returnable quantities, COGS, and profit view output.
   * Include both sale and sale return paths.
2. Green:
   * Move/wrap current inventory and COGS behavior in accounting current rules.
   * Rewire sale repo/report/dashboard call sites through `AccountingService`.
3. Refactor:
   * Keep valuation triggers and dirty valuation behavior unchanged.
   * Do not choose between average and FIFO as a correctness fix.

### Tests to add or update
- `tests/accounting/test_customer_sales_inventory_effects.py::test_sale_inventory_event_matches_current_sales_repo`
- `tests/accounting/test_customer_sales_inventory_effects.py::test_sale_return_inventory_event_matches_current_sales_repo`
- `tests/accounting/test_customer_sales_inventory_effects.py::test_sale_cogs_and_profit_match_current_views`
- Existing `tests/verification_tests/test_sale_stock_validation.py`
- Existing `tests/sales/test_sale_return_receivables.py`

### Implementation steps
1. Inspect sale inventory transaction rows and return rows.
2. Add sale inventory payload/result DTOs.
3. Add COGS/profit DTOs or compatibility bundles.
4. Implement wrappers in `inventory_rules.py` and `sales_rules.py`.
5. Add service methods.
6. Rewire sale repo write helpers and report/dashboard reads.
7. Keep schema views/triggers unchanged.
8. Document COGS source ambiguity in migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-018: Consolidate sale inventory, COGS, margin, and profit effects

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

### Behavior-preservation checks
- Inventory transaction rows match current behavior.
- Returnable quantities match current behavior.
- `sale_item_cogs`, `sale_item_fifo_cogs`, and `profit_loss_view` outputs used by reports are unchanged.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No valuation algorithm change.

### Acceptance criteria
- [ ] Sale inventory/COGS service methods exist.
- [ ] Current inventory/profit behavior is characterized.
- [ ] Original inventory/report call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore direct sales repo/report/dashboard inventory and COGS logic, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-003
- CS-ACC-015
- CS-ACC-010

### Follow-up tasks unlocked
- CS-ACC-019
- CS-ACC-020

## CS-ACC-019: Consolidate quotation totals, status, and conversion behavior

### Goal
Move current quotation financial summary, quotation status handling, and quotation-to-sale conversion financial side effects behind `AccountingService`.

### Why this task exists
Quotations share the `sales` table but must not behave like posted sales for payment and inventory. Conversion to sale creates accounting side effects through sale creation and stock checks.

### Source references from plan
- Accounting Areas To Consolidate: quotations and conversion to sale.
- Recommended Consolidation Phases: Quotation behavior.
- Manual Review Before Task Cards: quotation conversion side effects and stock checks.

### Source code references to verify
- `database/schema.py`: `sales.doc_type`, quotation payment blocking triggers.
- `database/repositories/sales_repo.py::create_quotation`
- `database/repositories/sales_repo.py::update_quotation`
- `database/repositories/sales_repo.py::convert_quotation_to_sale`
- `database/repositories/sales_repo.py::create_sale`
- `modules/sales/controller.py::_convert_to_sale`
- `modules/sales/controller.py::_generate_quotation_html_content`
- `resources/templates/invoices/quotation_invoice.html`
- `tests/sales/test_sales_form.py`

### Current behavior to preserve
Quotation totals, status values, expiry handling, payment blocking, conversion eligibility, created sale values, source quotation link, and stock checks remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/inventory_rules.py` only if conversion stock side effects are routed there.
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_quotation_financials(quotation_id: int | str) -> QuotationFinancials
AccountingService.validate_quotation_conversion(quotation_id: int | str) -> None
AccountingService.record_quotation_conversion_event(payload: QuotationConversionPayload) -> QuotationConversionResult
```

### Original call sites to rewire
- `database/repositories/sales_repo.py::create_quotation`
- `database/repositories/sales_repo.py::update_quotation`
- `database/repositories/sales_repo.py::convert_quotation_to_sale`
- `modules/sales/controller.py::_convert_to_sale`
- `modules/sales/controller.py::_generate_quotation_html_content`

### TDD plan
1. Red:
   * Add characterization tests for quotation totals and conversion output.
   * Assert quotations still reject payment and inventory posting until converted.
2. Green:
   * Wrap current quotation financial/conversion behavior in `sales_rules.py`.
   * Rewire repository/controller call sites through `AccountingService`.
3. Refactor:
   * Keep conversion behavior and status rules unchanged.
   * Do not split quotations into a new table or model.

### Tests to add or update
- `tests/accounting/test_customer_sales_quotation_behavior.py::test_quotation_financials_match_current_controller_context`
- `tests/accounting/test_customer_sales_quotation_behavior.py::test_quotation_conversion_matches_current_sales_repo`
- `tests/accounting/test_customer_sales_quotation_behavior.py::test_quotation_payment_blocking_is_preserved`

### Implementation steps
1. Inspect current quotation create/update/convert row changes.
2. Add quotation financial and conversion DTOs.
3. Implement service wrappers around current behavior.
4. Add `AccountingService` methods.
5. Rewire sales repo/controller conversion and quotation financial reads.
6. Keep schema guards unchanged.
7. Document conversion side-effect ambiguity in migration log.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-019: Consolidate quotation totals, status, and conversion behavior

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

### Behavior-preservation checks
- Quotation invoice values are unchanged.
- Conversion creates the same sale rows/items/source links.
- Quotation payment blocking remains enforced.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No quotation workflow redesign.

### Acceptance criteria
- [ ] Quotation service methods exist.
- [ ] Current quotation behavior is characterized.
- [ ] Original quotation call sites route through `AccountingService`.
- [ ] Migration log entry is appended.

### Rollback notes
Restore direct `SalesRepo` quotation logic and controller calls, remove service methods/tests/log entry.

### Dependencies
- CS-ACC-009
- CS-ACC-018

### Follow-up tasks unlocked
- CS-ACC-020

## CS-ACC-020: Cleanup migrated calculations and enforce guardrails

### Goal
Remove or lock down migrated Customer + Sales duplicate calculations only after all service routes are characterized and rewired.

### Why this task exists
During migration, duplicate logic may remain temporarily for safety. This final card cleans up only proven duplicates and strengthens guardrails so new Customer + Sales accounting behavior enters through `AccountingService`.

### Source references from plan
- Recommended Consolidation Phases: Cleanup and guardrail verification.
- Test Plan For Later.
- Manual Review Before Task Cards.

### Source code references to verify
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/reports/`
- `tests/accounting/test_customer_sales_accounting_guardrails.py`
- `database/repositories/sales_repo.py`
- `database/repositories/sale_payments_repo.py`
- `database/repositories/customer_advances_repo.py`
- `modules/customer/`
- `modules/sales/`
- `modules/reporting/`
- `modules/dashboard/`

### Current behavior to preserve
All migrated Customer + Sales accounting behavior must remain unchanged. Compatibility repository methods may remain if public callers still need them, but they should delegate to `AccountingService`.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/docs/accounting_current_rules_inventory.md`
- `modules/accounting/docs/accounting_consolidation_migration_log.md`

### Proposed AccountingService API
No new business API should be introduced unless a previous card missed a migrated slice. This card verifies existing Customer + Sales APIs.

### Original call sites to rewire
- Any remaining Customer + Sales accounting call site identified by guardrail tests or focused search.
- Compatibility wrappers in repositories may stay if they call `AccountingService`.

### TDD plan
1. Red:
   * Add or tighten tests that fail on direct Customer + Sales accounting calculations outside approved service/current-rule locations.
   * Add route tests proving migrated call sites use `AccountingService`.
2. Green:
   * Rewire any missed migrated call sites.
   * Delete only duplicate code proven unused by tests and search.
3. Refactor:
   * Keep cleanup surgical.
   * Do not correct accounting logic.

### Tests to add or update
- `tests/accounting/test_customer_sales_accounting_guardrails.py::test_migrated_customer_sales_slices_route_through_accounting_service`
- `tests/accounting/test_customer_sales_accounting_guardrails.py::test_no_direct_accounting_internal_imports_outside_accounting_module`
- Slice-specific tests added in previous cards as needed.

### Implementation steps
1. Run focused search for sale/customer accounting calculations in non-accounting modules.
2. Compare findings against migration log entries.
3. Rewire missed migrated call sites through service.
4. Delete only duplicate code made unreachable by completed cards.
5. Update `accounting_current_rules_inventory.md` Customer and Sales sections.
6. Ensure every completed CS card has a migration log entry.
7. Do not touch schema, triggers, or views.

### Migration log update
After implementing this card, append:

```markdown
## CS-ACC-020: Cleanup migrated calculations and enforce guardrails

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

### Behavior-preservation checks
- All Customer + Sales accounting tests pass.
- Guardrail tests pass.
- Migration log has entries for all implemented CS cards.
- No schema diff exists.

### Out of scope
- No accounting correction.
- No ledger redesign.
- No schema change.
- No unrelated refactor.
- No UI redesign.
- No ERP integration.
- No deletion of compatibility wrappers still used by public call sites.

### Acceptance criteria
- [ ] Migrated calculations route through `AccountingService`.
- [ ] Guardrail tests prevent direct accounting internals imports.
- [ ] Current-rules inventory documents Customer + Sales migrated behavior.
- [ ] Migration log entries exist for every completed card.

### Rollback notes
Restore any removed compatibility code and direct call paths from the previous commit. Remove only the cleanup guardrail additions and migration log entry if needed.

### Dependencies
- CS-ACC-001 through CS-ACC-019

### Follow-up tasks unlocked
- Final accounting scenario matrix population.
- Later correctness/correction phase.
- Future double-entry ledger design, if explicitly approved.

## Global Completion Criteria

The Customer + Sales consolidation phase is complete when:
- all customer/sales accounting calculations identified in the plan have an AccountingService route,
- original customer/sales modules no longer own migrated calculations,
- characterization tests cover each migrated slice,
- the migration log contains an entry for every completed card,
- no accounting behavior has intentionally changed,
- unresolved correctness questions are documented for the later scenario-matrix/correction phase.
