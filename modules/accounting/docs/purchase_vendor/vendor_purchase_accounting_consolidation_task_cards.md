# Vendor + Purchase Accounting Consolidation Task Cards

## Purpose

These cards consolidate current Vendor + Purchase accounting behavior into `modules/accounting/` without changing behavior. Current behavior is legacy behavior to characterize and preserve first. These cards do not assert that current accounting is correct.

## Non-Goals

- No accounting correctness changes
- No final ledger implementation
- No schema redesign
- No ERP integration
- No UI redesign unless required for existing call-site wiring
- No new external accounting dependency
- No migration or data backfill

## Execution Rules

- Implement one card at a time.
- Add characterization tests before changing production call sites.
- Run the focused tests after every card.
- Commit after every successful card.
- Do not combine unrelated cards.
- Do not proceed to write-side cards until read-side cards are stable.
- Route app modules through `AccountingService` only.
- Do not import `modules.accounting.ledger.*` or `modules.accounting.current_rules.*` from vendor, purchase, UI, report, inventory, bank, or repository modules.
- Do not delete old logic until tests prove the `AccountingService` wrapper preserves behavior.
- Document unclear behavior and preserve observed behavior instead of guessing.

## Recommended Implementation Order

1. VP-ACC-001: Verify scaffold and public accounting facade rules
2. VP-ACC-002: Define Vendor + Purchase accounting DTO/API contracts
3. VP-ACC-003: Consolidate purchase totals and discount calculations
4. VP-ACC-004: Consolidate purchase outstanding/payable calculations
5. VP-ACC-005: Consolidate purchase payment status calculations
6. VP-ACC-006: Consolidate vendor advance/credit balance calculations
7. VP-ACC-007: Consolidate vendor purchase totals and open purchase reads
8. VP-ACC-008: Consolidate vendor statement/history read model
9. VP-ACC-009: Consolidate purchase payment summary read model
10. VP-ACC-010: Consolidate vendor payment metadata validation
11. VP-ACC-011: Consolidate vendor payment current write behavior
12. VP-ACC-012: Consolidate vendor advance/deposit current write behavior
13. VP-ACC-013: Consolidate vendor credit application behavior
14. VP-ACC-014: Consolidate advance allocation/FIFO behavior
15. VP-ACC-015: Consolidate purchase return valuation calculations
16. VP-ACC-016: Consolidate purchase return settlement behavior
17. VP-ACC-017: Consolidate supplier refund behavior
18. VP-ACC-018: Consolidate bank/cash movement read behavior
19. VP-ACC-019: Consolidate inventory effects from purchases and returns
20. VP-ACC-020: Consolidate invoice/template/report financial value sourcing
21. VP-ACC-021: Cleanup migrated calculations and enforce guardrails

## VP-ACC-001: Verify scaffold and public accounting facade rules

### Goal
Confirm the accounting scaffold is ready for Vendor + Purchase migration and lock the rule that external modules call only `AccountingService`.

### Why this task exists
The audit shows behavior spread across schema, repositories, vendor/purchase controllers, UI widgets, reports, and templates. This card reduces migration risk by adding tests and documentation checks for the public facade before any behavior slice moves.

### Source references from audit
- `modules/accounting/docs/accounting_module_scaffold.md`: migration strategy and service rule
- `modules/accounting/service.py`: existing `AccountingService`
- `modules/accounting/dto.py`: existing DTO home
- `modules/accounting/current_rules/vendor_rules.py`: future extracted vendor rules home
- `modules/accounting/current_rules/purchase_rules.py`: future extracted purchase rules home
- Audit "Consolidation Candidates for Later": lists planned `AccountingService` APIs

### Current behavior to preserve
No runtime behavior changes. Existing vendor, purchase, report, bank, and inventory call sites must keep using their current paths until their own cards migrate them.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/dto.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/purchase_rules.py`

### Proposed AccountingService API
No business methods implemented in this card. Keep existing not-implemented methods and prepare later cards to add Vendor + Purchase methods through this class.

### Original call sites to rewire
None in this card.

### TDD plan
1. Red: Add a guardrail test that fails if vendor/purchase/UI/report modules import `modules.accounting.current_rules` or `modules.accounting.ledger` directly.
2. Green: Keep production behavior unchanged; only make the test pass if current imports already obey the rule.
3. Refactor: None unless the test helper itself needs small cleanup.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_accounting_guardrails.py::test_vendor_purchase_modules_do_not_import_accounting_internals`
- `tests/accounting/test_vendor_purchase_accounting_guardrails.py::test_accounting_service_is_public_facade`

### Implementation steps
1. Inspect current imports in vendor, purchase, repository, reporting, inventory, and widget files.
2. Add an AST or text-based guardrail test that scans tracked Python files in those areas.
3. Assert direct imports from `modules.accounting.current_rules` and `modules.accounting.ledger` are rejected outside `modules/accounting/`.
4. Assert `modules/accounting/service.py` defines `AccountingService`.
5. Do not wire any app code yet.

### Behavior-preservation checks
- Existing app imports remain unchanged.
- Guardrail test passes without modifying business behavior.
- No database, UI, or repository code changes.

### Out of scope
- Adding accounting logic
- Adding new DTO fields
- Rewiring vendor or purchase call sites
- Changing imports in production files unless an existing forbidden import is found
- Correcting accounting behavior

### Acceptance criteria
- [ ] Guardrail tests exist.
- [ ] Tests prove only `AccountingService` is the public accounting facade.
- [ ] No behavior is changed.
- [ ] Any unexpected forbidden import is documented before fixing.

### Rollback notes
Delete the new guardrail test file. No runtime rollback should be needed because production code is untouched.

### Dependencies
None.

### Follow-up tasks unlocked
- VP-ACC-002

## VP-ACC-002: Define Vendor + Purchase accounting DTO/API contracts

### Goal
Add the smallest DTOs and `AccountingService` method signatures needed by later Vendor + Purchase cards, with methods still unimplemented or delegating only when later cards add behavior.

### Why this task exists
The audit lists many candidate methods. Later cards need stable names and return shapes so tests and rewiring do not invent inconsistent APIs.

### Source references from audit
- Audit "Consolidation Candidates for Later": `get_vendor_balance`, `get_purchase_outstanding`, `get_vendor_advance_balance`, `get_vendor_statement`, `get_purchase_payment_status`, `get_purchase_financials`, `get_purchase_return_values`, `get_vendor_open_purchases`, write event APIs
- `modules/accounting/dto.py`: existing `VendorBalance`, `PurchaseOutstanding`, `AccountingEvent`
- `modules/accounting/service.py`: existing facade methods

### Current behavior to preserve
No existing call site behavior changes. Any new methods that are not migrated yet must raise the existing accounting not-implemented exception.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_purchase_totals(purchase_id: int) -> PurchaseTotals
AccountingService.get_purchase_outstanding(purchase_id: int) -> PurchaseOutstanding
AccountingService.get_purchase_payment_status(purchase_id: int) -> PurchasePaymentStatus
AccountingService.get_purchase_financials(purchase_id: int) -> PurchaseFinancials
AccountingService.get_vendor_advance_balance(vendor_id: int) -> VendorBalance
AccountingService.get_vendor_open_purchases(vendor_id: int) -> tuple[VendorOpenPurchase, ...]
AccountingService.get_vendor_statement(vendor_id: int, start_date: str | None = None, end_date: str | None = None) -> VendorStatement
```

### Original call sites to rewire
None in this card.

### TDD plan
1. Red: Add tests that instantiate `AccountingService` and assert the new method names exist and still raise `AccountingNotImplementedError` before their slice is implemented.
2. Green: Add minimal DTO dataclasses and method stubs.
3. Refactor: Remove any DTO not used by a named later card.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_accounting_contracts.py::test_vendor_purchase_service_contract_methods_exist`
- `tests/accounting/test_vendor_purchase_accounting_contracts.py::test_unmigrated_vendor_purchase_methods_raise_not_implemented`

### Implementation steps
1. Add only DTOs required by the planned cards.
2. Keep DTOs simple dataclasses using `Decimal` for money.
3. Add method stubs to `AccountingService`.
4. Reuse existing `VendorBalance` and `PurchaseOutstanding` where sufficient.
5. Do not import repository classes yet.

### Behavior-preservation checks
- Current app paths do not call the new stubs.
- Existing accounting scaffold tests still pass.
- No production behavior changes.

### Out of scope
- Implementing any calculation
- Adding a ledger model
- Designing final debit/credit rules
- Rewiring vendor/purchase modules

### Acceptance criteria
- [ ] DTOs cover later Vendor + Purchase read-side APIs.
- [ ] Unmigrated service methods fail loudly with `AccountingNotImplementedError`.
- [ ] No repository, controller, UI, schema, or report behavior changes.

### Rollback notes
Remove added DTOs and service stubs if the API shape is rejected. No data rollback needed.

### Dependencies
- VP-ACC-001

### Follow-up tasks unlocked
- VP-ACC-003
- VP-ACC-004
- VP-ACC-005
- VP-ACC-006

## VP-ACC-003: Consolidate purchase totals and discount calculations

### Goal
Move current purchase gross/subtotal/order-discount/net-total read calculations behind `AccountingService`, then rewire original read call sites for this slice.

### Why this task exists
Purchase totals feed outstanding, status, returns, reports, and invoice display. Moving totals first gives later cards a stable base without correcting any math.

### Source references from audit
- `database/schema.py:162` `purchases` stores `total_amount`, `order_discount`
- `database/schema.py:232` `purchase_items` stores quantity, purchase price, item discount
- `database/schema.py:2754` `purchase_detailed_totals` calculates gross subtotal, order discount, returned value, net purchase total
- `database/repositories/purchases_repo.py:58`, `91`, `102` list/search reads totals
- `database/repositories/purchases_repo.py:209` detail snapshot reads calculated totals
- `modules/purchase/form.py:1105`, `1132`, `1143`, `1429` calculates UI line totals, subtotal, order discount, total

### Current behavior to preserve
Preserve current item-level discount and order-level discount handling. Preserve the audit finding that no active purchase tax, freight, or extra-charge field was found. Do not add tax/freight behavior.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_purchase_totals(purchase_id: int) -> PurchaseTotals
AccountingService.preview_purchase_total(items: tuple[PurchaseTotalInputLine, ...], order_discount: Decimal) -> PurchaseTotals
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py` list/search/detail total reads
- `modules/purchase/form.py` total preview helpers
- Later invoice/report cards may use the same API but are not rewired here unless they already call the migrated helper.

### TDD plan
1. Red: Add characterization tests for line discount, order discount, zero discount, and returned-value net total using existing repository/view outputs as expected values.
2. Green: Implement service wrapper that delegates to current SQL view/repository math or exact copied current formula in `purchase_rules.py`.
3. Refactor: Rewire only the total-related call sites named in this card.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_purchase_totals.py::test_purchase_totals_match_purchase_detailed_totals_view`
- `tests/accounting/test_vendor_purchase_purchase_totals.py::test_preview_purchase_total_matches_purchase_form_current_math`
- `tests/purchase/test_purchase_form.py` update only if existing assertions need service wiring

### Implementation steps
1. Characterize current `purchase_detailed_totals` for purchases with item discount and order discount.
2. Add `PurchaseTotals` DTO with gross subtotal, order discount, returned value, net total, and stored header total if currently displayed.
3. Add `purchase_rules` helper that mirrors current formula.
4. Add `AccountingService.get_purchase_totals`.
5. Add `AccountingService.preview_purchase_total` for form-side preview only if needed to avoid duplicate UI math.
6. Rewire purchase list/detail/form call sites for total calculation through `AccountingService`.
7. Keep database view and old repo fields in place.

### Behavior-preservation checks
- Existing purchase list totals do not change.
- Purchase form displayed totals do not change.
- Stored `purchases.total_amount` behavior does not change.
- Returned value remains sourced from current return valuation view.

### Out of scope
- Adding tax, freight, or extra-charge fields
- Correcting discount allocation
- Changing persistence
- Changing purchase create/update writes
- Changing invoice template output beyond using the same values

### Acceptance criteria
- [ ] Service totals match current view/form outputs.
- [ ] Original total call sites use `AccountingService`.
- [ ] No schema or trigger changes.
- [ ] Correctness questions are documented, not fixed.

### Rollback notes
Restore total call sites to their previous direct formula/view reads and keep characterization tests as evidence. Remove service method only if no later card depends on it yet.

### Dependencies
- VP-ACC-002

### Follow-up tasks unlocked
- VP-ACC-004
- VP-ACC-015
- VP-ACC-020

## VP-ACC-004: Consolidate purchase outstanding/payable calculations

### Goal
Move current remaining due/payable calculations for purchases into `AccountingService` and rewire direct purchase outstanding reads.

### Why this task exists
Remaining due is recalculated in SQL views, repositories, forms, detail panels, and credit application paths. This is the core read-side payable slice used by payments, advances, status, and returns.

### Source references from audit
- `database/schema.py:2754` `purchase_detailed_totals`
- `database/repositories/vendor_advances_repo.py:479` `_get_purchase_remaining_due`
- `database/repositories/purchases_repo.py:1280` `get_remaining_due_header`
- `database/repositories/purchases_repo.py:1376` `get_purchase_remaining_due`
- `modules/purchase/payment_form.py:248` `_calculate_remaining_amount`
- `modules/purchase/details.py:56` displays remaining

### Current behavior to preserve
Remaining due remains current net total minus cleared direct payments minus applied vendor credit. Preserve current treatment of returns, refunds, and return credit as observed through existing repo/view outputs.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_purchase_outstanding(purchase_id: int) -> PurchaseOutstanding
AccountingService.get_purchase_remaining_due_header(purchase_id: int) -> PurchaseOutstanding
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py:get_remaining_due_header`
- `database/repositories/purchases_repo.py:get_purchase_remaining_due`
- `database/repositories/vendor_advances_repo.py:_get_purchase_remaining_due`
- `modules/purchase/payment_form.py:_calculate_remaining_amount`
- `modules/purchase/details.py:set_data` if it computes fallback due

### TDD plan
1. Red: Add characterization tests for no payment, partial payment, full payment, applied vendor credit, return-reduced net total, and overpayment/negative due if current behavior allows it.
2. Green: Implement service read that mirrors the current repository/view calculation.
3. Refactor: Rewire named call sites to service without changing database views or triggers.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_outstanding.py::test_purchase_outstanding_matches_repo_remaining_due`
- `tests/accounting/test_vendor_purchase_outstanding.py::test_purchase_outstanding_preserves_returns_payments_and_applied_credit`
- Existing tests to preserve: `tests/purchase/test_purchase_payment_negative_due_credit.py`, `tests/purchase/test_purchase_list_net_return_totals.py`

### Implementation steps
1. Write tests comparing `AccountingService.get_purchase_outstanding` to current repo methods.
2. Implement service method using current SQL/repo query shape.
3. Replace duplicate direct calculations in purchase payment form and vendor advance due helper.
4. Keep old repo methods as compatibility wrappers that call the service if needed.
5. Document any mismatch between `get_remaining_due_header` and `get_purchase_remaining_due`.

### Behavior-preservation checks
- Payment form due value is unchanged.
- Vendor credit application cap sees the same due.
- Purchase details remaining amount is unchanged.
- Existing negative/overpayment behavior is unchanged.

### Out of scope
- Correcting negative due behavior
- Changing paid amount rollups
- Changing status labels
- Moving payment write logic
- Changing return settlement

### Acceptance criteria
- [ ] Outstanding service output matches existing repo/view output.
- [ ] Direct outstanding call sites use `AccountingService`.
- [ ] Tests cover payments, credits, and returns.
- [ ] Any unclear due behavior is documented.

### Rollback notes
Restore rewired call sites to prior repo methods. Keep tests to show expected legacy behavior.

### Dependencies
- VP-ACC-003

### Follow-up tasks unlocked
- VP-ACC-005
- VP-ACC-009
- VP-ACC-013

## VP-ACC-005: Consolidate purchase payment status calculations

### Goal
Move current `paid`/`partial`/`unpaid` status calculation and recalculation entrypoint behind `AccountingService`.

### Why this task exists
Status is maintained by SQL triggers and Python repository code. This card centralizes the Python route while preserving trigger behavior.

### Source references from audit
- `database/schema.py:2190`, `2228`, `2266` paid/status triggers from purchase payments
- `database/schema.py:2581`, `2619`, `2657` applied advance/status triggers
- `database/repositories/purchases_repo.py:102` search/list status reads
- `database/repositories/purchases_repo.py:1304` `update_header_totals`
- `modules/purchase/model.py:22` status colors
- `tests/purchase/test_purchase_payment_status_recalculation.py`

### Current behavior to preserve
Status values remain exactly `paid`, `unpaid`, and `partial`. Current trigger-maintained fields remain in the database. Python recalculation must agree with current behavior; do not choose a new source of truth yet.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_purchase_payment_status(purchase_id: int) -> PurchasePaymentStatus
AccountingService.recalculate_purchase_payment_status(purchase_id: int) -> PurchasePaymentStatus
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py:update_header_totals`
- `database/repositories/purchases_repo.py` list/search display status reads where Python recalculation is used
- `modules/purchase/model.py:_payment_bg`
- `modules/purchase/details.py:set_data`

### TDD plan
1. Red: Add characterization tests that compare service status to stored `purchases.payment_status` after payment insert/update/delete, applied credit insert/delete, and purchase return.
2. Green: Implement service status logic by delegating to existing repo SQL or exact current recalculation.
3. Refactor: Rewire Python recalculation call sites to service; leave SQL triggers intact.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_payment_status.py::test_service_status_matches_stored_status_after_payment_changes`
- `tests/accounting/test_vendor_purchase_payment_status.py::test_service_status_matches_stored_status_after_credit_changes`
- Existing preservation: `tests/purchase/test_purchase_payment_status_recalculation.py`

### Implementation steps
1. Capture current status outcomes from existing tests and fixtures.
2. Add `PurchasePaymentStatus` DTO with status, paid amount, applied credit, and remaining due if existing UI needs them.
3. Implement service status read/recalc using current calculation.
4. Rewire `update_header_totals` to call service or make service call the same existing internal query; avoid recursion.
5. Update UI model/detail code only to consume the centralized status value.

### Behavior-preservation checks
- Status labels and colors do not change.
- Stored `paid_amount` and `advance_payment_applied` rollups do not change.
- SQL trigger behavior remains active.
- Deleting payments/credits produces the same status as before.

### Out of scope
- Removing triggers
- Redefining paid/partial thresholds
- Supporting pending vendor payments
- Changing status UI colors

### Acceptance criteria
- [ ] Service status matches stored status for characterized flows.
- [ ] Python status recalculation routes through `AccountingService`.
- [ ] SQL triggers remain untouched.
- [ ] No correctness fixes are mixed in.

### Rollback notes
Restore `update_header_totals` and UI status reads to prior code. Leave tests if they still document current behavior.

### Dependencies
- VP-ACC-004

### Follow-up tasks unlocked
- VP-ACC-009
- VP-ACC-011
- VP-ACC-013

## VP-ACC-006: Consolidate vendor advance/credit balance calculations

### Goal
Move signed vendor advance/credit balance reads into `AccountingService` and rewire vendor/purchase balance display paths.

### Why this task exists
Vendor credit balance is read through SQL view, vendor repo, advance repo, vendor controller, vendor details, and purchase form. This read-side slice must stabilize before advance writes and credit application move.

### Source references from audit
- `database/schema.py:829` `vendor_advances`
- `database/schema.py:2697` `v_vendor_advance_balance`
- `database/repositories/vendors_repo.py:68` `VendorsRepo.vendor_balances`
- `database/repositories/vendor_advances_repo.py:245` `get_balance`
- `modules/vendor/controller.py:183`, `223`, `332` balance hydration/display
- `modules/vendor/details.py:61` displays vendor credit
- `modules/purchase/form.py:504` displays vendor balance

### Current behavior to preserve
Balance remains the signed sum of `vendor_advances.amount`: positive rows grant credit and negative rows apply credit. Current labels that call it balance, advance, receivable, or credit remain unchanged in UI unless already centralized text exists.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_vendor_advance_balance(vendor_id: int) -> VendorBalance
AccountingService.get_vendor_advance_balances(vendor_ids: tuple[int, ...]) -> dict[int, VendorBalance]
```

### Original call sites to rewire
- `database/repositories/vendors_repo.py:vendor_balances`
- `database/repositories/vendor_advances_repo.py:get_balance`
- `modules/vendor/controller.py:_hydrate_visible_balances`
- `modules/vendor/controller.py:_vendor_credit_balance`
- `modules/purchase/form.py:_update_vendor_advance_display`

### TDD plan
1. Red: Add characterization tests for deposit, applied credit, return credit, and no-ledger vendor balance.
2. Green: Implement service balance using current view/fallback logic.
3. Refactor: Rewire display and batch hydration paths through the service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_vendor_balance.py::test_vendor_advance_balance_matches_current_view`
- `tests/accounting/test_vendor_purchase_vendor_balance.py::test_vendor_advance_balance_preserves_signed_rows`
- Existing preservation: `tests/vendor/test_vendor_list_caching.py`, `tests/vendor/test_vendor_advance.py`

### Implementation steps
1. Add service read for one vendor and optional batch read for list hydration.
2. Keep repo methods as wrappers if needed to avoid large controller diffs.
3. Preserve fallback behavior when `v_vendor_advance_balance` has no row.
4. Rewire vendor details and purchase form to use the public service route.
5. Do not change how advances are written.

### Behavior-preservation checks
- Vendor list balances stay identical.
- Vendor details credit display stays identical.
- Purchase form vendor balance text stays identical.
- No vendor advance rows are created or changed.

### Out of scope
- Correcting credit/advance naming
- Changing statement balances
- Moving advance write behavior
- Adding cutoff-date balance unless a current report path already requires it

### Acceptance criteria
- [ ] Service balance matches current view/repo output.
- [ ] Vendor and purchase display paths call `AccountingService`.
- [ ] Signed-row behavior is covered by tests.
- [ ] No write-side logic changes.

### Rollback notes
Restore balance call sites to `VendorAdvancesRepo`/`VendorsRepo`. No data rollback needed.

### Dependencies
- VP-ACC-002

### Follow-up tasks unlocked
- VP-ACC-007
- VP-ACC-008
- VP-ACC-012
- VP-ACC-013

## VP-ACC-007: Consolidate vendor purchase totals and open purchase reads

### Goal
Move vendor purchase total and open-purchase read models into `AccountingService`.

### Why this task exists
Open purchases are used by vendor credit allocation and vendor statement. Vendor purchase totals are used in summary and statement contexts. Moving them before write-side allocation reduces risk.

### Source references from audit
- `database/repositories/purchases_repo.py:1066` `list_purchases_by_vendor`
- `database/repositories/purchases_repo.py:1110` `get_purchase_totals_for_vendor`
- `database/repositories/purchases_repo.py:1349` `get_open_purchases_for_vendor`
- `modules/vendor/controller.py:293`, `295`, `319` open purchase helpers
- `modules/vendor/controller.py:361` FIFO preview input

### Current behavior to preserve
Vendor open purchases remain purchases with positive current remaining balance. Ordering and fields must match current controller/repository behavior, especially for FIFO allocation inputs.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_vendor_purchase_totals(vendor_id: int) -> VendorPurchaseTotals
AccountingService.get_vendor_open_purchases(vendor_id: int) -> tuple[VendorOpenPurchase, ...]
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py:list_purchases_by_vendor`
- `database/repositories/purchases_repo.py:get_purchase_totals_for_vendor`
- `database/repositories/purchases_repo.py:get_open_purchases_for_vendor`
- `modules/vendor/controller.py:_open_purchases_for_vendor`
- `modules/vendor/controller.py:_list_open_purchases_for_vendor`

### TDD plan
1. Red: Add characterization tests for vendor with no purchases, paid purchases, partial purchases, returned purchases, and applied credit.
2. Green: Implement service read model using existing queries and outstanding service.
3. Refactor: Rewire vendor controller helpers to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_open_purchases.py::test_vendor_open_purchases_match_current_repo_order_and_due`
- `tests/accounting/test_vendor_purchase_open_purchases.py::test_vendor_purchase_totals_match_current_repo_totals`
- Existing preservation: `tests/vendor/test_vendor_advance.py::test_fifo_preview...` if present

### Implementation steps
1. Characterize current open purchase order and fields.
2. Add DTOs for open purchase and vendor purchase totals.
3. Implement service methods by delegating to current repository SQL or extracting exact query behavior.
4. Rewire vendor controller open-purchase helper methods.
5. Keep old repository methods as compatibility wrappers until downstream cards finish.

### Behavior-preservation checks
- FIFO preview receives same purchase order and due amounts.
- Vendor summary totals remain unchanged.
- No purchases are filtered differently.

### Out of scope
- Changing FIFO allocation itself
- Changing vendor statement row construction
- Changing payment or credit writes
- Correcting returned purchase treatment

### Acceptance criteria
- [ ] Service open purchases match current repo output exactly.
- [ ] Vendor controller uses service for open-purchase reads.
- [ ] Tests cover ordering and due amounts.
- [ ] No write behavior changes.

### Rollback notes
Restore vendor controller helper calls to `PurchasesRepo`. Keep characterization tests for later retry.

### Dependencies
- VP-ACC-004
- VP-ACC-006

### Follow-up tasks unlocked
- VP-ACC-008
- VP-ACC-014

## VP-ACC-008: Consolidate vendor statement/history read model

### Goal
Move current vendor statement/history calculations into `AccountingService` and rewire the vendor history UI to use it.

### Why this task exists
Vendor statement math currently lives in the vendor controller and combines purchases, payments, refunds, deposits, and applied credits. This is a high-value read-side consolidation before write-side event movement.

### Source references from audit
- `modules/vendor/controller.py:847` `build_vendor_statement`
- `database/repositories/vendor_advances_repo.py:279` `list_ledger`
- `database/repositories/purchase_payments_repo.py:238` `list_payments_for_vendor`
- `database/repositories/purchases_repo.py:1066` `list_purchases_by_vendor`
- `modules/vendor/payment_history_view.py:138`, `191`, `548` displays/exports/prints statement
- `resources/templates/invoices/vendor_history_table.html:79`, `108`
- `tests/vendor/test_vendor_statement.py`

### Current behavior to preserve
Opening payable/credit, row order, effects, totals, closing balance, metadata display, print/export payloads, and labels must remain unchanged. Preserve current statement equation even if later accounting correction may change it.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_vendor_statement(
    vendor_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> VendorStatement
```

### Original call sites to rewire
- `modules/vendor/controller.py:build_vendor_statement`
- `modules/vendor/payment_history_view.py` only if it directly calculates statement totals
- `resources/templates/invoices/vendor_history_table.html` should keep same context shape unless unavoidable

### TDD plan
1. Red: Add service-level characterization tests that compare `AccountingService.get_vendor_statement` to current `VendorController.build_vendor_statement` output for existing scenarios.
2. Green: Move/wrap current statement construction into accounting current rules while preserving output shape.
3. Refactor: Make `VendorController.build_vendor_statement` delegate to `AccountingService`.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_vendor_statement.py::test_service_vendor_statement_matches_controller_payload`
- `tests/accounting/test_vendor_purchase_vendor_statement.py::test_vendor_statement_preserves_opening_and_closing_balances`
- Existing preservation: `tests/vendor/test_vendor_statement.py`

### Implementation steps
1. Identify current statement payload keys and row shapes from tests.
2. Add DTO or keep a plain mapping only if templates require dynamic keys.
3. Implement service statement method with the same ordering, signs, and labels.
4. Rewire controller method to call service.
5. Leave view/template rendering unchanged.
6. Document any unclear row effect semantics in the test or docstring.

### Behavior-preservation checks
- Vendor history dialog shows same rows and totals.
- Print/export output is unchanged.
- Opening payable and credit are unchanged for date-ranged statements.
- Existing vendor statement tests pass.

### Out of scope
- Correcting statement accounting equation
- Changing template layout
- Adding final party ledger
- Reworking payment history UI

### Acceptance criteria
- [ ] Service statement output matches controller legacy output.
- [ ] Controller delegates statement construction to `AccountingService`.
- [ ] Print/export payload shape remains compatible.
- [ ] Date-range behavior is characterized.

### Rollback notes
Restore `VendorController.build_vendor_statement` body from previous code and remove service delegation. No data rollback needed.

### Dependencies
- VP-ACC-006
- VP-ACC-007

### Follow-up tasks unlocked
- VP-ACC-011
- VP-ACC-012
- VP-ACC-017
- VP-ACC-020

## VP-ACC-009: Consolidate purchase payment summary read model

### Goal
Move latest payment, paid amount, applied credit, remaining due, and overpayment-credit display data for a purchase into `AccountingService`.

### Why this task exists
Purchase detail and controller code display payment information from multiple direct repository reads. This read model should centralize before payment write behavior moves.

### Source references from audit
- `database/repositories/purchase_payments_repo.py:212`, `238` list payment reads
- `database/repositories/purchase_payments_repo.py:284` latest payment read
- `modules/purchase/controller.py:477`, `494`, `507` latest payment, overpayment credited, refresh summary
- `modules/purchase/details.py:142` `set_payment_summary`
- `modules/purchase/details.py:56` financial display

### Current behavior to preserve
Latest payment selection, bank labels, overpayment credit display, paid amount, applied credit, remaining due, and status display must match current UI behavior.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_purchase_payment_summary(purchase_id: int) -> PurchasePaymentSummary
AccountingService.get_purchase_payment_history(purchase_id: int) -> tuple[PurchasePaymentRow, ...]
```

### Original call sites to rewire
- `modules/purchase/controller.py:_latest_purchase_payment`
- `modules/purchase/controller.py:_overpayment_credited`
- `modules/purchase/controller.py:_refresh_payment_summary`
- `modules/purchase/details.py:set_payment_summary`
- `database/repositories/purchase_payments_repo.py:get_latest_payment_for_purchase` may become wrapper

### TDD plan
1. Red: Add characterization tests for no payment, one payment, multiple payments, overpayment credit, and bank metadata label display.
2. Green: Implement service summary by using existing payment repo queries and outstanding/status service.
3. Refactor: Rewire controller summary methods to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_payment_summary.py::test_purchase_payment_summary_matches_current_controller_values`
- `tests/accounting/test_vendor_purchase_payment_summary.py::test_purchase_payment_summary_preserves_overpayment_credit`
- Existing preservation: `tests/vendor/test_purchase_payments.py`, `tests/purchase/test_purchase_payment_negative_due_credit.py`

### Implementation steps
1. Capture current controller summary output from fixtures.
2. Add summary DTO with latest payment, overpayment credited, paid, applied credit, remaining, and status.
3. Implement service method using current repo methods.
4. Rewire controller refresh path.
5. Keep existing detail widget API unless changing it is required for service output.

### Behavior-preservation checks
- Detail panel payment summary text/data is unchanged.
- Latest payment row selection is unchanged.
- Overpayment credit amount is unchanged.
- Existing payment tests pass.

### Out of scope
- Recording payments
- Changing overpayment conversion
- Changing payment form validation
- Changing status semantics

### Acceptance criteria
- [ ] Payment summary service matches current controller output.
- [ ] Controller reads summary through `AccountingService`.
- [ ] Tests cover overpayment display.
- [ ] No write behavior changes.

### Rollback notes
Restore controller helper methods to direct repo calls. Leave read-side tests for future use.

### Dependencies
- VP-ACC-004
- VP-ACC-005

### Follow-up tasks unlocked
- VP-ACC-011
- VP-ACC-020

## VP-ACC-010: Consolidate vendor payment metadata validation

### Goal
Move current payment method, bank account, instrument, ownership, active account, and clearing-state validation for vendor-side flows into `AccountingService`.

### Why this task exists
Validation is duplicated across forms, repositories, and schema triggers. This card centralizes Python validation while preserving database trigger enforcement.

### Source references from audit
- `database/schema.py:668`, `684` refund ownership triggers
- `database/schema.py:700`, `717` refund active account triggers
- `database/schema.py:748`, `767` purchase payment vendor account ownership triggers
- `database/schema.py:786`, `803` purchase payment active account triggers
- `database/schema.py:860`, `869` vendor advance card method triggers
- `database/schema.py:878`, `887` vendor advance cleared-only triggers
- `database/schema.py:896`, `909`, `922`, `939` vendor advance account ownership/active triggers
- `database/schema.py:2310`, `2396` purchase payment method checks
- `database/repositories/vendor_advances_repo.py:428` `_validate_payment_metadata`
- `modules/purchase/form.py:1343` initial payment validation
- `modules/purchase/payment_form.py:564`, `648` validation/payload

### Current behavior to preserve
Preserve current cleared-only vendor payment and vendor advance behavior, card rejection for vendor advances, inactive account rejection, vendor bank ownership checks, and method/instrument requirements. Do not add pending/bounced lifecycle support.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/validators.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.validate_vendor_payment_metadata(metadata: VendorPaymentMetadata) -> None
AccountingService.validate_supplier_refund_metadata(metadata: SupplierRefundMetadata) -> None
```

### Original call sites to rewire
- `database/repositories/vendor_advances_repo.py:_validate_payment_metadata`
- `database/repositories/purchase_payments_repo.py:record_payment`
- `modules/purchase/form.py:_validate_initial_payment`
- `modules/purchase/payment_form.py:_validate_payment`
- Purchase return/refund UI path if it uses matching metadata validation

### TDD plan
1. Red: Add characterization tests for cash, bank transfer/cheque-like methods, missing instrument, inactive company bank, inactive vendor bank, wrong-vendor bank, card rejection, and uncleared state rejection.
2. Green: Implement service validation by extracting current Python checks and preserving DB-trigger-backed errors where current Python allows DB enforcement.
3. Refactor: Rewire forms and repos to call service validation.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_payment_metadata_validation.py::test_vendor_payment_metadata_preserves_current_method_rules`
- `tests/accounting/test_vendor_purchase_payment_metadata_validation.py::test_vendor_payment_metadata_rejects_inactive_accounts`
- Existing preservation: `tests/purchase/test_purchase_vendor_payments_cleared_only.py`, `tests/purchase/test_purchase_bank_account_active_validation.py`

### Implementation steps
1. Record exact exception types/messages currently asserted by tests.
2. Add metadata DTOs only for fields already used.
3. Extract repository validation logic to accounting validators/current rules.
4. Keep DB triggers as final enforcement.
5. Rewire UI form validation and repo validation to service.
6. Avoid broad validation redesign.

### Behavior-preservation checks
- Same invalid inputs are rejected.
- Same valid payment metadata is accepted.
- Existing tests expecting DB enforcement still pass.
- No payment rows are written differently.

### Out of scope
- Adding payment methods
- Supporting pending/bounced vendor payment state
- Replacing schema triggers
- Changing error wording unless tests show it is not user-visible

### Acceptance criteria
- [ ] Vendor payment metadata validation goes through `AccountingService`.
- [ ] Existing bank/account validation tests pass.
- [ ] Schema trigger behavior remains unchanged.
- [ ] No write-side event behavior changes beyond validation call path.

### Rollback notes
Restore repo/form validation calls to their previous local helpers. Keep accounting validator code unused until revisited.

### Dependencies
- VP-ACC-001
- VP-ACC-002

### Follow-up tasks unlocked
- VP-ACC-011
- VP-ACC-012
- VP-ACC-017

## VP-ACC-011: Consolidate vendor payment current write behavior

### Goal
Move current purchase/vendor payment recording behavior behind `AccountingService.record_vendor_payment_event`.

### Why this task exists
Vendor payments affect `purchase_payments`, purchase rollups/status, audit logs, overpayment conversion to vendor credit, bank/cash reports, and UI summaries. This write-side slice must move after read-side outstanding/status/payment summary are stable.

### Source references from audit
- `database/schema.py:585` `purchase_payments`
- `database/repositories/purchase_payments_repo.py:15` `record_payment`
- `database/repositories/purchase_payments_repo.py:188` `update_clearing_state`
- `modules/purchase/controller.py:1261` purchase payment action
- `modules/purchase/controller.py:559` initial payment on purchase add
- `database/schema.py:2190`, `2228`, `2266` paid/status triggers
- `tests/vendor/test_purchase_payments.py`
- `tests/purchase/test_purchase_payment_negative_due_credit.py`

### Current behavior to preserve
Payments remain cleared-only. Payments write `purchase_payments`. Overpayment may create vendor credit using existing behavior. Audit side effects and status recalculation remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.preview_vendor_payment_effect(payload: VendorPaymentPayload) -> VendorPaymentEffect
AccountingService.record_vendor_payment_event(payload: VendorPaymentPayload) -> VendorPaymentResult
AccountingService.update_vendor_payment_state(payment_id: int, clearing_state: str) -> None
```

### Original call sites to rewire
- `database/repositories/purchase_payments_repo.py:record_payment`
- `database/repositories/purchase_payments_repo.py:update_clearing_state`
- `modules/purchase/controller.py:_payment`
- `modules/purchase/controller.py:_handle_add_dialog_accept` initial payment path

### TDD plan
1. Red: Add characterization tests for exact current writes: normal payment, full payment, overpayment to credit, cleared-only enforcement, metadata persistence, and rollback on failure.
2. Green: Implement service method as a thin wrapper around existing repository behavior or extracted exact logic.
3. Refactor: Rewire controller/repo entrypoints so external callers use `AccountingService`.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_vendor_payment_event.py::test_record_vendor_payment_event_matches_purchase_payment_repo`
- `tests/accounting/test_vendor_purchase_vendor_payment_event.py::test_record_vendor_payment_event_preserves_overpayment_credit`
- Existing preservation: `tests/vendor/test_purchase_payments.py`, `tests/purchase/test_purchase_vendor_payments_cleared_only.py`

### Implementation steps
1. Freeze current payment behavior with tests before moving code.
2. Add payload/result DTOs with only existing fields.
3. Add preview method only if needed by UI; it must not write.
4. Move or wrap `PurchasePaymentsRepo.record_payment` logic behind service.
5. Make existing repo method delegate to service or service call the repo; avoid circular imports.
6. Rewire purchase controller payment paths to service.

### Behavior-preservation checks
- Same rows appear in `purchase_payments`.
- Same overpayment credit rows appear in `vendor_advances`.
- Same status/paid rollups result.
- Same exceptions occur for invalid metadata.

### Out of scope
- Supporting pending/bounced states
- Changing overpayment policy
- Changing audit log semantics
- Changing bank ledger views
- Correcting accounting entries

### Acceptance criteria
- [ ] Payment write path routes through `AccountingService`.
- [ ] Current payment tests pass.
- [ ] Overpayment credit behavior is preserved.
- [ ] Old scattered payment calculations are not silently deleted until covered.

### Rollback notes
Restore controller and repo calls to `PurchasePaymentsRepo.record_payment`. If partial service code remains unused, leave it only if tests still pass or remove it.

### Dependencies
- VP-ACC-004
- VP-ACC-005
- VP-ACC-009
- VP-ACC-010

### Follow-up tasks unlocked
- VP-ACC-018
- VP-ACC-020

## VP-ACC-012: Consolidate vendor advance/deposit current write behavior

### Goal
Move current vendor advance/deposit/credit grant behavior behind `AccountingService.record_vendor_advance_event`.

### Why this task exists
Vendor advances are signed credit ledger rows used for deposits, manual credit, return credit, payment metadata, balance display, statement rows, and credit application. This write path must be centralized before allocation and application logic move.

### Source references from audit
- `database/schema.py:829` `vendor_advances`
- `database/repositories/vendor_advances_repo.py:114` `grant_credit`
- `database/repositories/vendor_advances_repo.py:428` `_validate_payment_metadata`
- `modules/vendor/controller.py:769`, `1249` advance dialog/open grant credit dialog
- `modules/vendor/controller.py:396` `_grant_credit_and_auto_apply`
- `tests/vendor/test_vendor_advance.py`

### Current behavior to preserve
Positive `vendor_advances.amount` rows grant credit/deposit/return credit. Payment metadata is preserved. Existing validation, audit behavior, and balance impact remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.record_vendor_advance_event(payload: VendorAdvancePayload) -> VendorAdvanceResult
AccountingService.get_vendor_credit_ledger(vendor_id: int) -> tuple[VendorCreditLedgerRow, ...]
```

### Original call sites to rewire
- `database/repositories/vendor_advances_repo.py:grant_credit`
- `modules/vendor/controller.py:_on_apply_advance_dialog`
- `modules/vendor/controller.py:_open_grant_credit_dialog`
- `modules/vendor/controller.py:_grant_credit_and_auto_apply` grant part only

### TDD plan
1. Red: Add characterization tests for manual credit, deposit with metadata, temporary vendor bank metadata, return credit source type, and validation failures.
2. Green: Implement service wrapper/extraction preserving current insert fields.
3. Refactor: Rewire vendor controller grant paths to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_vendor_advance_event.py::test_record_vendor_advance_event_preserves_signed_credit_rows`
- `tests/accounting/test_vendor_purchase_vendor_advance_event.py::test_record_vendor_advance_event_preserves_payment_metadata`
- Existing preservation: `tests/vendor/test_vendor_advance.py`

### Implementation steps
1. Characterize row fields written by `VendorAdvancesRepo.grant_credit`.
2. Add minimal payload/result DTOs.
3. Route metadata validation through VP-ACC-010 service method.
4. Implement `record_vendor_advance_event` with exact current write behavior.
5. Rewire vendor controller grant paths.
6. Keep existing repo method as compatibility wrapper if needed.

### Behavior-preservation checks
- Same `vendor_advances` rows are written.
- Same balance is produced after grant.
- Same vendor statement rows appear later.
- Same validation failures occur.

### Out of scope
- Applying credit to purchases
- FIFO allocation
- Correcting credit/deposit naming
- Adding ledger journal entries

### Acceptance criteria
- [ ] Vendor advance grants route through `AccountingService`.
- [ ] Existing metadata and validation behavior is preserved.
- [ ] Tests cover signed-row balance impact.
- [ ] No statement or allocation behavior changes yet.

### Rollback notes
Restore vendor controller and repo paths to `VendorAdvancesRepo.grant_credit`.

### Dependencies
- VP-ACC-006
- VP-ACC-010

### Follow-up tasks unlocked
- VP-ACC-013
- VP-ACC-014
- VP-ACC-017
- VP-ACC-018

## VP-ACC-013: Consolidate vendor credit application behavior

### Goal
Move current applying of vendor credit to purchases behind `AccountingService.record_vendor_credit_application`.

### Why this task exists
Credit application is a write-side accounting event that writes negative vendor advance rows and affects purchase due/status. It must use centralized outstanding and balance reads.

### Source references from audit
- `database/repositories/vendor_advances_repo.py:45` `apply_credit_to_purchase`
- `database/repositories/vendor_advances_repo.py:479` `_get_purchase_remaining_due`
- `database/schema.py:2480` no-overdraw trigger
- `database/schema.py:2499` due-cap trigger
- `database/schema.py:2581`, `2619`, `2657` applied advance/status triggers
- `modules/purchase/controller.py:1209` `apply_vendor_credit`
- `modules/vendor/controller.py:396` auto-apply orchestration

### Current behavior to preserve
Applied credit is a negative `vendor_advances` row with `source_type='applied_to_purchase'`. Current overdraw, due cap, status, and rollback behavior remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/validators.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.validate_vendor_credit_application(payload: VendorCreditApplicationPayload) -> None
AccountingService.record_vendor_credit_application(payload: VendorCreditApplicationPayload) -> VendorCreditApplicationResult
```

### Original call sites to rewire
- `database/repositories/vendor_advances_repo.py:apply_credit_to_purchase`
- `modules/purchase/controller.py:apply_vendor_credit`
- `modules/vendor/controller.py:_grant_credit_and_auto_apply` application part

### TDD plan
1. Red: Add characterization tests for valid application, cross-vendor rejection, overdraw rejection, due-cap rejection, status update, and deletion/recalc if current tests cover it.
2. Green: Implement service wrapper/extraction preserving current insert and validation behavior.
3. Refactor: Rewire controller paths to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_credit_application.py::test_record_vendor_credit_application_preserves_negative_advance_row`
- `tests/accounting/test_vendor_purchase_credit_application.py::test_record_vendor_credit_application_preserves_due_and_balance_caps`
- Existing preservation: `tests/vendor/test_vendor_advance.py`, `tests/purchase/test_purchase_payment_status_recalculation.py`

### Implementation steps
1. Characterize current negative row fields and status effects.
2. Add payload/result DTOs.
3. Implement validation using service outstanding and vendor balance reads.
4. Keep DB triggers active as final enforcement.
5. Rewire purchase controller manual apply path.
6. Rewire vendor controller auto-apply loop only after VP-ACC-014 if FIFO logic is part of the same call path.

### Behavior-preservation checks
- Same negative row is written.
- Same purchase due/status results.
- Same exceptions are raised for invalid application.
- Same rollback behavior in auto-apply flows.

### Out of scope
- Changing FIFO allocation
- Changing credit source naming
- Correcting due cap semantics
- Replacing database triggers

### Acceptance criteria
- [ ] Manual credit application routes through `AccountingService`.
- [ ] Tests prove signed-row and status behavior.
- [ ] Validation remains behavior-preserving.
- [ ] No allocation order changes.

### Rollback notes
Restore calls to `VendorAdvancesRepo.apply_credit_to_purchase`. Service method can remain unused until fixed.

### Dependencies
- VP-ACC-004
- VP-ACC-005
- VP-ACC-006

### Follow-up tasks unlocked
- VP-ACC-014
- VP-ACC-018

## VP-ACC-014: Consolidate advance allocation/FIFO behavior

### Goal
Move current vendor grant-credit allocation preview and auto-apply FIFO behavior into `AccountingService`.

### Why this task exists
FIFO allocation currently lives in the vendor controller. It depends on open purchases, due amounts, vendor balance, grant credit, and credit application. This card centralizes the orchestration after those pieces exist.

### Source references from audit
- `modules/vendor/controller.py:361` `_build_grant_credit_allocation_preview`
- `modules/vendor/controller.py:396` `_grant_credit_and_auto_apply`
- `modules/vendor/controller.py:293`, `295`, `319` open purchase helpers
- `database/repositories/purchases_repo.py:1349` open purchases
- `tests/vendor/test_vendor_advance.py` covers FIFO preview, auto-apply atomicity, rollback

### Current behavior to preserve
Allocation order remains purchase date, then purchase id. Excess credit remains unapplied. Auto-apply rollback behavior remains unchanged if one application fails after credit grant.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.preview_vendor_advance_allocation(
    vendor_id: int,
    amount: Decimal,
) -> VendorAdvanceAllocationPreview
AccountingService.record_vendor_advance_with_auto_apply(
    payload: VendorAdvancePayload,
) -> VendorAdvanceAllocationResult
```

### Original call sites to rewire
- `modules/vendor/controller.py:_build_grant_credit_allocation_preview`
- `modules/vendor/controller.py:_grant_credit_and_auto_apply`
- Vendor advance dialog flow that displays preview

### TDD plan
1. Red: Add service-level characterization tests for FIFO order, partial allocation, exact allocation, excess credit, no open purchases, and rollback on failed application.
2. Green: Move/wrap controller FIFO logic into accounting current rules.
3. Refactor: Make vendor controller delegate preview and auto-apply to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_advance_allocation.py::test_preview_vendor_advance_allocation_preserves_fifo_order`
- `tests/accounting/test_vendor_purchase_advance_allocation.py::test_record_vendor_advance_with_auto_apply_preserves_rollback`
- Existing preservation: `tests/vendor/test_vendor_advance.py`

### Implementation steps
1. Capture current preview payload shape and UI expectations.
2. Add preview/result DTOs or preserve mapping shape if UI expects dicts.
3. Implement preview using `get_vendor_open_purchases`.
4. Implement auto-apply using `record_vendor_advance_event` and `record_vendor_credit_application`.
5. Keep transaction boundaries identical to current controller behavior.
6. Rewire controller methods to service.

### Behavior-preservation checks
- Preview rows and amounts match current UI.
- Auto-applied credit rows match current behavior.
- Excess credit remains on vendor balance.
- Rollback leaves no partial grant/application if current behavior does that.

### Out of scope
- New allocation rules
- User-selectable allocation
- Correcting FIFO semantics
- Ledger posting design

### Acceptance criteria
- [ ] FIFO preview is service-owned.
- [ ] Auto-apply orchestration is service-owned.
- [ ] Tests prove order, excess, and rollback.
- [ ] Controller no longer owns allocation math.

### Rollback notes
Restore vendor controller FIFO methods and direct repo calls. No schema rollback needed.

### Dependencies
- VP-ACC-007
- VP-ACC-012
- VP-ACC-013

### Follow-up tasks unlocked
- VP-ACC-021

## VP-ACC-015: Consolidate purchase return valuation calculations

### Goal
Move current purchase return value preview and stored return valuation reads behind `AccountingService`.

### Why this task exists
Return values affect net purchase totals, refundable amounts, vendor statement, reports, and settlement. Valuation must be centralized before return write/settlement moves.

### Source references from audit
- `database/schema.py:345` `purchase_return_snapshots`
- `database/schema.py:1301` return snapshot trigger
- `database/schema.py:1350`, `1358` snapshot immutability guards
- `database/schema.py:3116` `purchase_return_valuations`
- `database/repositories/purchases_repo.py:1140`, `1181` return value reads/totals
- `modules/purchase/return_form.py:379`, `556`, `599` return value preview
- `tests/purchase/test_purchase_return_order_discount_allocation.py`
- `tests/purchase/test_purchase_return_snapshots.py`

### Current behavior to preserve
Return valuation stays snapshot-driven for persisted returns. UI preview preserves current item discount and order discount allocation behavior. Snapshot immutability remains database-enforced.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.preview_purchase_return_effect(payload: PurchaseReturnPreviewPayload) -> PurchaseReturnEffect
AccountingService.get_purchase_return_values(purchase_id: int) -> tuple[PurchaseReturnValue, ...]
AccountingService.get_purchase_return_totals(purchase_id: int) -> PurchaseReturnTotals
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py:list_return_values_by_purchase`
- `database/repositories/purchases_repo.py:purchase_return_totals`
- `modules/purchase/return_form.py:_compute_return_value_factor`
- `modules/purchase/return_form.py:_refresh_totals`
- `modules/purchase/return_form.py:payload`

### TDD plan
1. Red: Add characterization tests for preview value with item discount, order discount allocation, partial returns, multiple returns, and stored snapshot totals.
2. Green: Implement service read/preview using exact current formula and views.
3. Refactor: Rewire return form preview and repo read helpers to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_return_valuation.py::test_return_preview_preserves_order_discount_allocation`
- `tests/accounting/test_vendor_purchase_return_valuation.py::test_return_values_match_snapshot_view`
- Existing preservation: `tests/purchase/test_purchase_return_order_discount_allocation.py`, `tests/purchase/test_purchase_return_snapshots.py`

### Implementation steps
1. Capture current return preview formula from return form.
2. Add return preview/value DTOs.
3. Implement preview method without writing.
4. Implement stored value read using `purchase_return_valuations`.
5. Rewire return form and repo read methods.
6. Keep snapshot triggers untouched.

### Behavior-preservation checks
- Return form displayed value is unchanged.
- Persisted return valuation rows are unchanged.
- Purchase net totals after returns are unchanged.
- Snapshot immutability tests still pass.

### Out of scope
- Recording returns
- Changing inventory transaction rows
- Correcting discount allocation
- Changing refund/credit settlement

### Acceptance criteria
- [ ] Return valuation preview is service-owned.
- [ ] Stored return valuation reads go through service.
- [ ] Tests cover discount allocation and snapshots.
- [ ] No return write behavior changes.

### Rollback notes
Restore return form and repo valuation reads to prior local code. Snapshot data is untouched.

### Dependencies
- VP-ACC-003

### Follow-up tasks unlocked
- VP-ACC-016
- VP-ACC-020

## VP-ACC-016: Consolidate purchase return settlement behavior

### Goal
Move current purchase return write and settlement behavior behind `AccountingService.record_purchase_return_event`.

### Why this task exists
Purchase returns mix inventory movement, snapshot valuation, refund/credit settlement, status recalculation, and vendor credit reinstatement. This write-side slice is high risk and must follow return valuation and read-side payable work.

### Source references from audit
- `database/repositories/purchases_repo.py:651`, `679` `record_return`, `_record_return`
- `database/repositories/purchases_repo.py:1216` `fetch_purchase_financials`
- `database/schema.py:317` `inventory_transactions`
- `database/schema.py:1301` return snapshot trigger
- `database/schema.py:1370` return transaction immutability guard
- `modules/purchase/controller.py:1125` return action
- `modules/purchase/return_form.py:794` settlement helpers
- `tests/purchase/test_purchase_return.py`
- `tests/purchase/test_purchase_return_settlement_excess.py`

### Current behavior to preserve
Return writes remain `inventory_transactions.transaction_type='purchase_return'`. Settlement may create supplier refund rows or vendor return credit rows. Existing excess-funded return behavior and status recalculation remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_purchase_financials(purchase_id: int) -> PurchaseFinancials
AccountingService.record_purchase_return_event(payload: PurchaseReturnPayload) -> PurchaseReturnResult
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py:record_return`
- `database/repositories/purchases_repo.py:_record_return`
- `database/repositories/purchases_repo.py:fetch_purchase_financials`
- `modules/purchase/controller.py:_return`
- `modules/purchase/return_form.py` settlement financial reads

### TDD plan
1. Red: Add characterization tests for return with no settlement, refund now, credit note, prior refund, prior return credit, funded excess reinstatement, stock validation, and rollback.
2. Green: Implement service wrapper/extraction preserving current transaction boundaries and writes.
3. Refactor: Rewire controller/repo return entrypoints to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_return_event.py::test_record_purchase_return_event_preserves_inventory_and_snapshot_rows`
- `tests/accounting/test_vendor_purchase_return_event.py::test_record_purchase_return_event_preserves_excess_settlement_behavior`
- Existing preservation: `tests/purchase/test_purchase_return.py`, `tests/purchase/test_purchase_return_settlement_excess.py`

### Implementation steps
1. Characterize exact rows written for return inventory, snapshots, refunds, and credits.
2. Add payload/result DTOs using existing form payload fields.
3. Move financial read to `get_purchase_financials`.
4. Implement return event as a thin wrapper around current repository behavior first.
5. Rewire purchase controller return action.
6. Keep schema triggers and guards untouched.

### Behavior-preservation checks
- Same inventory return rows are written.
- Same snapshot valuation rows are created.
- Same refund/credit settlement rows are created.
- Same purchase status and remaining due result.
- Same rollback behavior.

### Out of scope
- Correcting return accounting
- Changing stock validation
- Changing snapshot immutability
- Changing UI flow
- Designing ledger entries

### Acceptance criteria
- [ ] Purchase return write path routes through `AccountingService`.
- [ ] Tests cover inventory, valuation, settlement, and rollback.
- [ ] Existing return behavior is unchanged.
- [ ] Any unclear settlement behavior is documented.

### Rollback notes
Restore return controller/repo calls to `PurchasesRepo.record_return`. No schema rollback needed.

### Dependencies
- VP-ACC-004
- VP-ACC-005
- VP-ACC-015

### Follow-up tasks unlocked
- VP-ACC-017
- VP-ACC-018
- VP-ACC-019
- VP-ACC-020

## VP-ACC-017: Consolidate supplier refund behavior

### Goal
Move current supplier refund write/read behavior behind `AccountingService.record_supplier_refund_event`.

### Why this task exists
Supplier refunds are vendor-side cash/bank inflows connected to purchase returns and reports. They need their own slice after return settlement is characterized.

### Source references from audit
- `database/schema.py:636` `purchase_refunds`
- `database/schema.py:668`, `684` refund ownership triggers
- `database/schema.py:700`, `717` active account triggers
- `database/repositories/purchases_repo.py:992` supplier refund write
- `database/repositories/purchases_repo.py:1216` refund totals in financials
- `database/repositories/reporting_repo.py:910` disbursements/refunds by day
- `tests/purchase/test_purchase_refund_now.py`
- `tests/reporting/test_payment_reports_vendor_refunds.py`

### Current behavior to preserve
Refunds remain stored in `purchase_refunds`. Current refund cap, metadata, ownership, active account validation, prior refund/credit-note behavior, rollback, statement effect, and report effect remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.record_supplier_refund_event(payload: SupplierRefundPayload) -> SupplierRefundResult
AccountingService.get_supplier_refunds_for_purchase(purchase_id: int) -> tuple[SupplierRefundRow, ...]
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py` refund write helper near line 992
- `database/repositories/purchases_repo.py:fetch_purchase_financials`
- Purchase return settlement path from VP-ACC-016
- Reporting paths may be rewired later in VP-ACC-018/020

### TDD plan
1. Red: Add characterization tests for refund now, refund cap, metadata persistence, prior refunds, prior credit notes, rollback, and statement/report effect.
2. Green: Implement service wrapper/extraction preserving current writes.
3. Refactor: Rewire return settlement refund branch and direct refund reads to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_supplier_refund.py::test_record_supplier_refund_event_preserves_purchase_refund_row`
- `tests/accounting/test_vendor_purchase_supplier_refund.py::test_supplier_refund_preserves_prior_refund_and_credit_note_behavior`
- Existing preservation: `tests/purchase/test_purchase_refund_now.py`

### Implementation steps
1. Characterize `purchase_refunds` row fields and financial effect.
2. Add refund payload/result DTOs.
3. Use VP-ACC-010 validation for metadata.
4. Implement service method preserving current cap and rollback.
5. Rewire return settlement refund path.
6. Keep DB triggers active.

### Behavior-preservation checks
- Same refund rows are written.
- Same bank metadata is stored.
- Same vendor statement effect appears.
- Same report net-outflow effect appears.

### Out of scope
- Changing refund cap formula
- Changing bank ledger view
- Correcting refund accounting
- Adding refund lifecycle states

### Acceptance criteria
- [ ] Supplier refund write path routes through `AccountingService`.
- [ ] Tests cover cap, metadata, prior settlements, rollback.
- [ ] Existing purchase refund tests pass.
- [ ] No schema changes.

### Rollback notes
Restore refund branch to previous `PurchasesRepo` helper. Existing rows need no migration.

### Dependencies
- VP-ACC-010
- VP-ACC-016

### Follow-up tasks unlocked
- VP-ACC-018
- VP-ACC-020

## VP-ACC-018: Consolidate bank/cash movement read behavior

### Goal
Move current vendor-side cash/bank movement reads for purchase payments, vendor advances, and supplier refunds behind `AccountingService`.

### Why this task exists
Bank/cash reporting currently reads vendor disbursements and supplier refunds through schema views and reporting repo SQL. This should be centralized after write-side payment/refund/advance paths are stable.

### Source references from audit
- `database/schema.py:3071`, `3229` `v_bank_ledger`, `v_bank_ledger_ext`
- `database/repositories/reporting_repo.py:910` `purchase_disbursements_by_day`
- `modules/reporting/financial_reports.py:102`, `115`, `162`, `181`
- `modules/reporting/payment_reports.py:140`, `296`
- `modules/reporting/comprehensive_payments_reports.py:162`, `183`, `237`, `306`
- `tests/reporting/test_purchase_disbursements_refunds.py`
- `tests/reporting/test_payment_reports_vendor_refunds.py`

### Current behavior to preserve
Vendor payments and vendor advances remain cash/bank outflows where current views treat them that way. Supplier refunds remain inflows that reduce net disbursement. Cleared-only assumptions remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/reports/ar_ap_summary.py` if existing report boundary fits
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_vendor_cash_movements(start_date: str | None = None, end_date: str | None = None) -> tuple[VendorCashMovement, ...]
AccountingService.get_bank_ledger(start_date: str | None = None, end_date: str | None = None, account_id: int | None = None) -> tuple[BankLedgerRow, ...]
```

### Original call sites to rewire
- `database/repositories/reporting_repo.py:purchase_disbursements_by_day`
- `modules/reporting/financial_reports.py`
- `modules/reporting/payment_reports.py`
- `modules/reporting/comprehensive_payments_reports.py` vendor-side purchase payment/refund portions

### TDD plan
1. Red: Add characterization tests for bank ledger rows from vendor payment, vendor advance with bank metadata, supplier refund, and report net disbursement.
2. Green: Implement service reads using current views/report SQL.
3. Refactor: Rewire reporting repo or report modules to use service for vendor-side cash movement values.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_cash_movements.py::test_vendor_cash_movements_match_current_reporting_repo`
- `tests/accounting/test_vendor_purchase_cash_movements.py::test_bank_ledger_preserves_vendor_payment_advance_and_refund_rows`
- Existing preservation: `tests/reporting/test_purchase_disbursements_refunds.py`, `tests/reporting/test_payment_reports_vendor_refunds.py`

### Implementation steps
1. Characterize current `v_bank_ledger` and `v_bank_ledger_ext` rows.
2. Add DTOs for vendor cash movement and bank ledger row.
3. Implement read service using current SQL views.
4. Rewire reporting repo methods or modules with the least diff.
5. Preserve date filters and cleared-only semantics.

### Behavior-preservation checks
- Payment reports net outflow is unchanged.
- Financial report AP/cash values are unchanged.
- Comprehensive payment reports still show same vendor payments/refunds.
- Bank ledger rows match current view output.

### Out of scope
- Replacing bank ledger views
- Adding bank reconciliation
- Changing pending/cleared behavior
- Correcting debit/credit direction

### Acceptance criteria
- [ ] Vendor cash movement reads route through `AccountingService`.
- [ ] Reporting values remain unchanged.
- [ ] Tests cover payments, advances, and refunds.
- [ ] Current bank views stay in place.

### Rollback notes
Restore reporting code to direct `ReportingRepo` SQL/view reads. No data rollback needed.

### Dependencies
- VP-ACC-011
- VP-ACC-012
- VP-ACC-017

### Follow-up tasks unlocked
- VP-ACC-020
- VP-ACC-021

## VP-ACC-019: Consolidate inventory effects from purchases and returns

### Goal
Move current purchase and purchase-return inventory accounting event reads/writes behind `AccountingService` without changing stock behavior.

### Why this task exists
Purchases and returns create inventory transactions and affect valuation. This cross-module effect should move only after purchase and return financial behavior is stable.

### Source references from audit
- `database/schema.py:317` `inventory_transactions`
- `database/schema.py:1078`, `1093` returned item guards
- `database/schema.py:1301` return snapshot trigger
- `database/repositories/purchases_repo.py:363` purchase creation writes inventory rows
- `database/repositories/purchases_repo.py:433` purchase update rebuilds purchase inventory rows
- `database/repositories/purchases_repo.py:651`, `679` purchase return writes return inventory
- `database/repositories/purchases_repo.py:1059` delete purchase deletes inventory transactions
- `database/repositories/purchases_repo.py:1159` returnable quantity map
- `modules/inventory/model.py:36`, `modules/inventory/transactions.py:221`
- `modules/inventory/stock_valuation.py:155`
- `tests/inventory/test_valuation_dirty_rebuild.py`
- `tests/inventory/test_inventory_txn_seq_ordering.py`

### Current behavior to preserve
Purchase create/update/delete and purchase return must create, rebuild, or delete the same inventory transaction rows in the same order. Stock valuation dirty/rebuild behavior and return snapshot behavior must remain unchanged.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.record_purchase_inventory_event(payload: PurchaseInventoryPayload) -> PurchaseInventoryResult
AccountingService.record_purchase_return_inventory_event(payload: PurchaseReturnInventoryPayload) -> PurchaseReturnInventoryResult
AccountingService.get_purchase_returnable_quantities(purchase_id: int) -> dict[int, Decimal]
AccountingService.get_inventory_accounting_events(source_type: str | None = None, source_id: int | None = None) -> tuple[InventoryAccountingEvent, ...]
```

### Original call sites to rewire
- `database/repositories/purchases_repo.py:create_purchase`
- `database/repositories/purchases_repo.py:update_purchase`
- `database/repositories/purchases_repo.py:delete_purchase`
- `database/repositories/purchases_repo.py:get_returnable_map`
- `modules/inventory/model.py`
- `modules/inventory/transactions.py`
- `modules/inventory/stock_valuation.py` only for purchase/return accounting reads if direct values are duplicated

### TDD plan
1. Red: Add characterization tests for inventory rows on purchase create, update, delete, return, returnable quantities, valuation dirty rebuild, and transaction sequence order.
2. Green: Implement service wrapper/extraction preserving current repository writes and order.
3. Refactor: Rewire purchase repo inventory side-effect blocks to service.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_inventory_effects.py::test_purchase_inventory_event_preserves_transaction_rows`
- `tests/accounting/test_vendor_purchase_inventory_effects.py::test_purchase_return_inventory_event_preserves_returnable_quantities_and_sequence`
- Existing preservation: `tests/inventory/test_valuation_dirty_rebuild.py`, `tests/inventory/test_inventory_txn_seq_ordering.py`

### Implementation steps
1. Characterize current `inventory_transactions` rows for purchase create/update/delete/return.
2. Add minimal DTOs for event payload/result.
3. Extract only purchase-related inventory behavior, not all inventory accounting.
4. Rewire purchase repo methods one by one.
5. Keep return snapshot triggers untouched.
6. Verify sequence ordering with existing tests.

### Behavior-preservation checks
- Same transaction row count and fields.
- Same valuation dirty/rebuild behavior.
- Same returnable quantity results.
- Same transaction ordering.

### Out of scope
- Full inventory valuation redesign
- Ledger inventory accounts
- Changing stock validation
- Changing return snapshot logic
- Refactoring inventory UI

### Acceptance criteria
- [ ] Purchase inventory effects route through `AccountingService`.
- [ ] Return inventory effects route through `AccountingService`.
- [ ] Existing inventory tests pass.
- [ ] No schema or valuation correction changes.

### Rollback notes
Restore purchase repository inventory write blocks. No data rollback should be required if tests use isolated databases.

### Dependencies
- VP-ACC-016

### Follow-up tasks unlocked
- VP-ACC-021

## VP-ACC-020: Consolidate invoice/template/report financial value sourcing

### Goal
Move Vendor + Purchase invoice, template, and report financial value sourcing to `AccountingService` while preserving current output.

### Why this task exists
Display/report code has its own financial math and fallback behavior. This card makes reports and templates consume centralized read models after core read/write slices are stable.

### Source references from audit
- `modules/purchase/controller.py:778`, `842` purchase invoice context generation
- `widgets/invoice_preview.py:96` invoice preview data with hardcoded discount zero fallback
- `resources/templates/invoices/purchase_invoice.html:68`, `140`, `151`, `164`
- `resources/templates/invoices/vendor_history_table.html:79`, `108`
- `modules/reporting/purchase_reports.py:414`, `441`, `604`, `687`, `706`, `731`, `766`
- `modules/reporting/vendor_aging_reports.py:83`, `159`, `358`
- `modules/reporting/financial_reports.py:102`, `115`, `162`, `181`
- `tests/purchase/test_purchase_controller.py`
- `tests/reporting/test_vendor_aging_cutoff.py`
- `tests/reporting/test_purchase_reports_net_totals.py`
- `tests/reporting/test_purchase_reports_financial_events.py`
- `tests/reporting/test_purchase_reports_quantity_base.py`

### Current behavior to preserve
Purchase invoice totals, payment status, bank labels, paid amount, payment rows, vendor history template totals, purchase reports, vendor aging, financial reports, and CSV/HTML/export values must remain unchanged. Preserve current invoice fallback that treats purchase totals as subtotal and sets line/order discounts to zero unless tests prove another current source.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/reports/ar_ap_summary.py`
- `modules/accounting/reports/party_ledger.py`
- `modules/accounting/dto.py`

### Proposed AccountingService API
```python
AccountingService.get_purchase_invoice_financials(purchase_id: int) -> PurchaseInvoiceFinancials
AccountingService.get_purchase_reports(start_date: str | None = None, end_date: str | None = None) -> PurchaseReportBundle
AccountingService.get_vendor_aging(cutoff_date: str) -> VendorAgingReport
AccountingService.get_ap_summary(cutoff_date: str | None = None) -> APSummary
AccountingService.get_payment_activity(start_date: str | None = None, end_date: str | None = None) -> PaymentActivityReport
```

### Original call sites to rewire
- `modules/purchase/controller.py:_print_purchase_invoice`
- `modules/purchase/controller.py:_generate_invoice_html_content`
- `widgets/invoice_preview.py:_prepare_invoice_data`
- `modules/reporting/purchase_reports.py`
- `modules/reporting/vendor_aging_reports.py`
- `modules/reporting/financial_reports.py`
- `modules/reporting/payment_reports.py`
- `modules/reporting/comprehensive_payments_reports.py`

### TDD plan
1. Red: Add characterization tests for invoice context, invoice preview fallback, purchase report net totals, financial events, vendor aging cutoff, payment reports, and exports if current tests cover them.
2. Green: Implement service read models by composing previously migrated service methods and current report SQL.
3. Refactor: Rewire display/report call sites to service with unchanged template context keys.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_invoice_financials.py::test_purchase_invoice_financials_preserve_controller_context`
- `tests/accounting/test_vendor_purchase_reports.py::test_purchase_reports_preserve_current_net_totals`
- `tests/accounting/test_vendor_purchase_reports.py::test_vendor_aging_preserves_cutoff_behavior`
- Existing preservation: listed reporting and purchase controller tests above

### Implementation steps
1. Capture current invoice/template context keys.
2. Add invoice/report DTOs only where they reduce ambiguity; keep mappings where templates require them.
3. Implement invoice financial service using purchase totals, payment summary, and current bank label reads.
4. Implement report service methods as thin wrappers over current report SQL first.
5. Rewire invoice preview/controller and report modules one at a time.
6. Preserve export row shapes.

### Behavior-preservation checks
- Rendered invoice HTML is unchanged.
- Vendor history print/export is unchanged.
- Purchase report totals/events are unchanged.
- Vendor aging buckets are unchanged.
- Payment report vendor refund netting is unchanged.

### Out of scope
- UI redesign
- Template redesign
- Correcting invoice discount fallback
- Replacing all reporting infrastructure
- Adding new report columns

### Acceptance criteria
- [ ] Invoice and report financial values route through `AccountingService`.
- [ ] Template context remains compatible.
- [ ] Existing report tests pass.
- [ ] Unclear invoice fallback is documented, not corrected.

### Rollback notes
Restore invoice/report modules to direct repository/reporting repo reads. Templates need no rollback if context shape was preserved.

### Dependencies
- VP-ACC-008
- VP-ACC-009
- VP-ACC-015
- VP-ACC-017
- VP-ACC-018

### Follow-up tasks unlocked
- VP-ACC-021

## VP-ACC-021: Cleanup migrated calculations and enforce guardrails

### Goal
Remove or demote only migrated duplicate Vendor + Purchase calculations after tests prove `AccountingService` owns those slices.

### Why this task exists
The migration intentionally keeps old logic temporarily. After all slices are routed through the service, stale duplicate calculations should be removed or turned into compatibility wrappers to prevent drift.

### Source references from audit
- Audit summary: behavior scattered across `database/schema.py`, repositories, `modules/vendor/`, `modules/purchase/`, reporting modules, templates, widgets, and tests
- Audit "Highest-risk areas": status rollups, vendor credit balance/application, purchase return/refund behavior, bank/cash assumptions, invoice/report display math
- Audit "Risks / Unknowns": trigger/repo status ownership, invoice fallback, bank ledger authority, return settlement, no tax/freight fields

### Current behavior to preserve
All previously migrated behavior remains unchanged. Cleanup must not remove schema triggers, views, or compatibility methods still used by unmigrated or external code unless tests prove they are dead and the project owner approves.

### Target accounting module location
- `modules/accounting/service.py`
- `modules/accounting/current_rules/*.py`
- `modules/accounting/validators.py`
- `modules/accounting/docs/accounting_current_rules_inventory.md`
- Tests under `tests/accounting/`

### Proposed AccountingService API
No new API required. Confirm all APIs added by prior cards are used consistently.

### Original call sites to rewire
- Any remaining direct migrated calculation in:
  - `database/repositories/purchases_repo.py`
  - `database/repositories/purchase_payments_repo.py`
  - `database/repositories/vendor_advances_repo.py`
  - `database/repositories/vendors_repo.py`
  - `modules/vendor/controller.py`
  - `modules/purchase/controller.py`
  - `modules/purchase/form.py`
  - `modules/purchase/payment_form.py`
  - `modules/purchase/return_form.py`
  - `modules/reporting/*`
  - `widgets/invoice_preview.py`

### TDD plan
1. Red: Strengthen guardrail tests to fail if migrated calculation patterns remain in original modules outside allowed compatibility wrappers.
2. Green: Remove only proven duplicate migrated logic or convert it to a service call.
3. Refactor: Update docs with unresolved behavior and remaining source-of-truth questions.

### Tests to add or update
- `tests/accounting/test_vendor_purchase_accounting_guardrails.py::test_migrated_vendor_purchase_slices_route_through_accounting_service`
- `tests/accounting/test_vendor_purchase_accounting_guardrails.py::test_no_direct_accounting_internal_imports_outside_accounting_module`

### Implementation steps
1. List every completed card and its migrated call sites.
2. Search for remaining duplicate calculation formulas from migrated slices.
3. Keep compatibility methods that are public repository APIs, but make them call service.
4. Remove imports made unused by the migration.
5. Update `accounting_current_rules_inventory.md` with preserved current behavior and unresolved correction questions.
6. Run the full focused Vendor + Purchase accounting test set.

### Behavior-preservation checks
- All card-specific tests still pass.
- Existing vendor, purchase, reporting, and inventory tests still pass.
- No forbidden imports exist outside accounting module.
- No migrated calculation has a second owner outside approved wrappers.

### Out of scope
- Removing SQL triggers/views
- Final double-entry ledger implementation
- Correcting accounting behavior
- Broad refactors
- Deleting repository APIs used outside the app without approval

### Acceptance criteria
- [ ] All migrated Vendor + Purchase accounting routes go through `AccountingService`.
- [ ] Duplicate migrated calculations are removed or wrappers only.
- [ ] Guardrail tests enforce the public facade rule.
- [ ] Current-rules inventory documents unresolved behavior.
- [ ] No production behavior intentionally changed.

### Rollback notes
Revert only cleanup edits that removed/rewired duplicate logic. Service implementations from earlier cards can remain if their tests still pass.

### Dependencies
- VP-ACC-001 through VP-ACC-020

### Follow-up tasks unlocked
- Scenario matrix completion for correctness review
- Later final ledger/double-entry design
- Explicit accounting correction phase

## Global Completion Criteria

The Vendor + Purchase consolidation phase is complete when:

- all vendor/purchase accounting calculations identified in the audit have an `AccountingService` route
- original modules no longer own migrated calculations
- characterization tests cover each migrated slice
- no accounting behavior has intentionally changed
- unresolved correctness questions are documented for the later scenario-matrix/correction phase
