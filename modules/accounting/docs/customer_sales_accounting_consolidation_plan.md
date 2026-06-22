# Customer + Sales Accounting Consolidation Plan

## Purpose

This plan documents how to consolidate current Customer + Sales accounting behavior into `modules/accounting/` without changing behavior first.

Current behavior is legacy behavior to characterize and preserve. This document does not assert that current accounting is correct, and it does not create task cards yet.

## Current Repo State

- The original accounting docs requested in earlier work are deleted at their old paths in this worktree.
- Copies exist under `modules/accounting/docs/sales_vendor/` and should be treated as the source material unless the deleted files are restored.
- The Vendor + Purchase consolidation already shows the target pattern:
  - Public facade: `modules/accounting/service.py` exposes `AccountingService`.
  - Current behavior homes: `modules/accounting/current_rules/*`.
  - DTO boundary: `modules/accounting/dto.py`.
  - Validation boundary: `modules/accounting/validators.py`.
  - Vendor/Purchase tests: `tests/accounting/test_vendor_purchase_*`.
  - Guardrail tests block non-accounting modules from importing `modules.accounting.current_rules` or `modules.accounting.ledger`.
  - Rewired call sites use `AccountingService(...)`, not accounting internals.
- `modules/accounting/current_rules/customer_rules.py` and `modules/accounting/current_rules/sales_rules.py` currently contain only placeholder module docs.
- `AccountingService` has placeholder customer/sale methods such as `get_customer_balance`, `get_sale_outstanding`, `get_customer_credit_balance`, `record_customer_receipt_event`, and `record_sale_return_event`.

## Non-Goals

- No accounting correctness changes.
- No schema, trigger, or view changes.
- No ledger implementation.
- No UI redesign.
- No new external accounting dependency.
- No migration or data backfill.
- No task-card generation in this step.
- No correction of known duplicate or inconsistent logic during consolidation.

## Source Areas To Preserve First

### Schema, Triggers, And Views

`database/schema.py` owns the main Customer + Sales accounting storage and database-side behavior:

- `sales`, including sale/quotation split through `doc_type`, stored `payment_status`, `paid_amount`, and `advance_payment_applied`.
- `sale_items`, including item price and discount data.
- `sale_payments`, including receipts/refunds, payment methods, clearing state, bank metadata, and overpayment conversion columns.
- `sale_payment_state_reversals`, including reopening authorization.
- `customer_advances`, including deposits, applied credits, and return credits.
- `sale_return_snapshots`, including return value and COGS reversal snapshots.
- Sale/customer guards for quotation payment blocking, sale return immutability, customer credit overdraw, credit application due caps, and sale/customer identity changes after accounting activity.
- Rollup triggers for `sales.paid_amount`, `sales.advance_payment_applied`, and `sales.payment_status`.
- `sale_detailed_totals`, `sale_receivable_totals`, `sale_financial_events`, `sale_item_cogs`, `sale_item_fifo_cogs`, `profit_loss_view`, `v_customer_advance_balance`, `v_bank_ledger`, and `v_bank_ledger_ext`.

### Repositories

- `database/repositories/sales_repo.py`
  - Sale and quotation creation, update, delete, conversion, stock posting, stock checks, status refresh, sale returns, receivable position, sale totals, customer sale list, and detail snapshots.
- `database/repositories/sale_payments_repo.py`
  - Receipt/refund recording, clearing state lifecycle, reopening, payment history, overpayment-to-credit behavior, and customer payment listing.
- `database/repositories/customer_advances_repo.py`
  - Customer deposits, return credits, credit application, credit balance, and credit ledger reads.
- `database/repositories/customers_repo.py`
  - Customer list/detail snapshot, credit balance, open due summary, and customer profile reads.

### Customer UI

- `modules/customer/controller.py`
  - Customer financial panel enrichment, history print, payment/advance actions, credit application, eligible sale selection, and payment history.
- `modules/customer/history.py`
  - Customer statement/history timeline from sales, payments, returns, advances, applied credits, and summaries.
- `modules/customer/details.py`
  - Customer financial display values.
- `modules/customer/payment_history_view.py` and `modules/customer/receipt_dialog.py`
  - Customer payment display and receipt UI.

### Sales UI

- `modules/sales/controller.py`
  - Sale detail panel, sale financial fetches, payment form flow, return flow, customer credit application, sale invoice generation, quotation invoice generation, and quotation conversion.
- `modules/sales/details.py`
  - Sale detail financial display.
- `modules/sales/payment_form.py`
  - Payment amount, method, bank, instrument, and clearing validation.
- `modules/sales/return_form.py`
  - Return quantity, refund/credit choice, return value preview, and cash refund input.
- `modules/sales/form.py`, `modules/sales/items.py`, and `modules/sales/model.py`
  - Sale/quotation totals, item values, status display, and list model behavior.

### Reports, Dashboard, Templates, And Widgets

- `modules/reporting/customer_aging_reports.py`
  - AR aging and customer due buckets.
- `modules/reporting/sales_reports.py`
  - Sales reports, return summaries, margins, and exported values.
- `modules/reporting/payment_reports.py`, `modules/reporting/enhanced_payment_reports.py`, and `modules/reporting/comprehensive_payments_reports.py`
  - Customer receipts/refunds and payment status views.
- `modules/reporting/financial_reports.py`
  - AR/AP summary and profit/loss.
- `modules/dashboard/*`
  - Sales, receivable, payment, and KPI summaries.
- `resources/templates/invoices/sale_invoice.html`
  - Sale invoice totals, paid amount, due amount, applied credit, return credit, and payment details.
- `resources/templates/invoices/quotation_invoice.html`
  - Quotation item totals and grand total.
- `resources/templates/invoices/customer_history.html` and `customer_history_table.html`
  - Customer statement/history rows and summaries.
- `widgets/invoice_preview.py`
  - Purchase invoice preview uses the accounting-service pattern. Sales invoice generation currently remains in `modules/sales/controller.py`.

## Accounting Areas To Consolidate

1. Customer balance and receivables.
2. Sale totals, item discounts, order discounts, paid amount, due amount, and payment status.
3. Sale payment receipts/refunds, clearing lifecycle, payment methods, and cash/bank movement.
4. Overpayment conversion into customer credit.
5. Customer advances, deposits, return credits, applied credit, and credit balance.
6. Sale returns, customer cash refund, customer credit settlement, return snapshots, COGS reversal, and inventory restoration.
7. Quotations and conversion to sale.
8. Inventory stock decrement, stock restoration, COGS, margin, and profit.
9. Reports, dashboards, invoices, statements, and exports.
10. Validation and status rules.

## Proposed AccountingService Expansion

Add later, not in this doc task:

```python
AccountingService.get_sale_totals(sale_id)
AccountingService.get_sale_financial_summary(sale_id)
AccountingService.get_sale_outstanding(sale_id)
AccountingService.get_sale_payment_status(sale_id)
AccountingService.get_sale_payment_history(sale_id)
AccountingService.get_customer_credit_balance(customer_id)
AccountingService.get_customer_open_sales(customer_id)
AccountingService.get_customer_statement(customer_id, start_date=None, end_date=None)
AccountingService.preview_customer_payment_effect(payload)
AccountingService.record_customer_payment_event(payload)
AccountingService.update_customer_payment_state(...)
AccountingService.record_customer_credit_event(payload)
AccountingService.preview_customer_credit_allocation(...)
AccountingService.record_customer_credit_application_event(payload)
AccountingService.preview_sale_return_effect(payload)
AccountingService.record_sale_return_event(payload)
AccountingService.record_sale_inventory_event(payload)
AccountingService.record_sale_return_inventory_event(payload)
AccountingService.get_sale_returnable_quantities(sale_id)
AccountingService.get_sale_invoice_financials(sale_id)
AccountingService.get_quotation_financials(quotation_id)
AccountingService.get_ar_summary(cutoff_date=None)
AccountingService.get_customer_aging(cutoff_date)
```

Likely target files:

- `modules/accounting/service.py`
- `modules/accounting/dto.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/reports/ar_ap_summary.py`
- `modules/accounting/reports/party_ledger.py`
- `modules/accounting/validators.py`

## Recommended Consolidation Phases

### 1. Foundation Alignment

Add Customer + Sales accounting contract and guardrail tests that mirror the Vendor + Purchase pattern.

Verification focus:

- `AccountingService` remains the only public accounting facade.
- Customer, sales, reporting, dashboard, repository, and widget modules do not import `modules.accounting.current_rules` or `modules.accounting.ledger`.
- New Customer + Sales API methods either raise `AccountingNotImplementedError` or route to characterized current behavior.

### 2. Read-Only Sale Financial Summaries

Move sale totals, returned value, paid amount, applied credit, due amount, and payment status reads behind `AccountingService`.

Current behavior sources:

- `sale_detailed_totals`
- `sale_receivable_totals`
- `SalesRepo.get_sale_totals`
- `SalesRepo.get_receivable_position`
- `SalesRepo.get_sale_detail_summary`
- `SalesRepo.get_sale_detail_snapshot`
- `SalesRepo._refresh_sale_payment_status`

### 3. Read-Only Customer Balances And Statements

Move customer credit balance, open sales, receivable summaries, and statement/history reads behind `AccountingService`.

Current behavior sources:

- `v_customer_advance_balance`
- `CustomerAdvancesRepo.get_balance`
- `CustomerAdvancesRepo.list_ledger`
- `CustomersRepo.get_detail_snapshot`
- `CustomerHistoryService.full_history`
- `CustomerHistoryService.timeline`
- `CustomerController._details_enrichment`
- `CustomerController._eligible_sales_for_application`

### 4. Display, Report, Template, And Export Rewiring

Rewire display-only values to read from `AccountingService` after characterization tests prove parity.

Targets:

- Sale detail panel.
- Customer financial panel.
- Sale invoice and quotation invoice.
- Customer history print.
- AR aging.
- Sales reports.
- Payment reports.
- Financial reports.
- Dashboard summaries.
- CSV/HTML exports.

### 5. Customer Payment Current Behavior

Move receipt/refund preview and recording behavior behind `AccountingService` without changing payment semantics.

Current behavior sources:

- `SalePaymentsRepo.record_payment_with_conn`
- `SalePaymentsRepo.record_payment`
- `SalePaymentsRepo.update_clearing_state`
- `SalePaymentsRepo.reopen_clearing_state`
- `SalePaymentsRepo.list_by_sale`
- `SalePaymentsRepo.list_by_customer`
- `SalesPaymentForm`
- `SalesController._record_payment`
- `SalesController._on_payment_status_change_requested`

### 6. Customer Credit And Advance Current Behavior

Move customer deposit, return credit, applied credit, credit balance, and allocation behavior behind `AccountingService`.

Current behavior sources:

- `CustomerAdvancesRepo.grant_credit`
- `CustomerAdvancesRepo.add_return_credit`
- `CustomerAdvancesRepo.apply_credit_to_sale`
- `CustomerAdvancesRepo.add_deposit`
- `CustomerAdvancesRepo.apply_to_sale`
- `CustomerController._on_record_advance`
- `CustomerController._on_apply_advance`
- `SalesController._maybe_apply_customer_credit_to_sale`
- `SalesController._on_apply_credit`

### 7. Sale Return And Refund Current Behavior

Move sale return preview, posting, cash refund, return credit, and receivable effects behind `AccountingService`.

Current behavior sources:

- `SalesRepo.record_return`
- `SalesRepo.sale_return_totals`
- `SaleReturnForm`
- `SalesController._return`
- `SalesController._handle_return_dialog_accept`
- `sale_return_snapshots`
- `customer_advances.source_type='return_credit'`

### 8. Inventory, COGS, And Profit Side Effects

Move sale inventory events, sale return inventory events, COGS reads, and profit/margin reads behind accounting service APIs where they are accounting values.

Current behavior sources:

- `SalesRepo._insert_inventory_sale`
- `SalesRepo._check_stock_availability`
- `inventory_transactions`
- `sale_item_cogs`
- `sale_item_fifo_cogs`
- `profit_loss_view`
- `sale_financial_events`
- inventory restoration done by sale returns.

### 9. Quotation Behavior

Move quotation financial reads and quotation-to-sale conversion financial checks behind service APIs only after sale read-side behavior is stable.

Current behavior sources:

- `sales.doc_type='quotation'`
- Quotation payment-blocking triggers.
- `SalesRepo.create_quotation`
- `SalesRepo.update_quotation`
- `SalesRepo.convert_quotation_to_sale`
- `SalesController._convert_to_sale`
- `SalesController._generate_quotation_html_content`
- `resources/templates/invoices/quotation_invoice.html`

### 10. Cleanup And Guardrail Verification

Remove migrated duplicate calculations only after service parity tests and focused rewiring tests pass.

Keep:

- Database constraints and triggers that preserve data integrity.
- Characterization tests that document legacy behavior.
- Guardrail tests that keep non-accounting modules out of accounting internals.

## First Three Future Task-Card Categories

### 1. Customer/Sales Accounting Contracts And Guardrails

- Goal: DTO/API shape and import rules.
- Depends on: current Vendor + Purchase pattern.
- Risk: low.
- Tests: contract and guardrail tests.

### 2. Sale Read-Side Financial Summaries

- Goal: totals, paid, credit applied, remaining due, and status.
- Depends on: contracts.
- Risk: medium.
- Tests: characterization against `sale_detailed_totals`, `sale_receivable_totals`, and `SalesRepo`.

### 3. Customer Balance And Statement Reads

- Goal: credit balance, open receivables, and history timeline.
- Depends on: sale read-side summaries.
- Risk: medium.
- Tests: characterization against `CustomersRepo`, `CustomerHistoryService`, and AR aging.

## Manual Review Before Task Cards

- Duplicate sale payment status logic in schema triggers and `SalesRepo._refresh_sale_payment_status`.
- Difference between `posted` plus `cleared` in some customer queries and `cleared` only in triggers/reports.
- Overpayment-to-credit behavior in `SalePaymentsRepo`.
- Return settlement math in `SalesRepo.record_return`.
- COGS source: average-cost view and FIFO view both exist.
- Quotation conversion side effects and stock checks.
- Invoice totals in `modules/sales/controller.py` may not match UI/report values.
- Existing deleted docs at requested paths versus copies in `modules/accounting/docs/sales_vendor/`.

## Test Plan For Later

- Add characterization tests first.
- Preserve current behavior before rewiring.
- Separate read-side and write-side tests.
- Use isolated SQLite fixtures.
- Compare service output to current repository/view output.
- Add UI/report/template snapshot checks only where values are rendered.
- Do not correct known bugs during consolidation.
- Do not run broad tests unless explicitly asked.

## Assumptions

- `modules/accounting/docs/sales_vendor/*` remains the source for copied accounting planning docs while old paths are deleted.
- Schema, triggers, views, repositories, and UI behavior stay unchanged during this documentation task.
- Current behavior is legacy behavior, not necessarily correct behavior.
- Future prompts will create task cards from this plan.
