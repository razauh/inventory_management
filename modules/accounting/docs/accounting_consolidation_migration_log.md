# Accounting Consolidation Migration Log

## Purpose
This file records accounting behavior that has been migrated into `modules/accounting/`.

It is not a correctness document.
It does not claim migrated behavior is final or correct.
It records where legacy/current behavior moved and which application call sites now use `AccountingService`.

## Rules
- Add one entry after each completed task card.
- State whether behavior changed. During consolidation, behavior should normally be "None intended."
- Record unresolved correctness questions for the later scenario-matrix/correction phase.
- Do not use this file to define final accounting rules.

## Entries

## CS-ACC-001: Verify Customer + Sales accounting facade guardrails

- Migrated behavior:
  - None. Foundation guardrail card only.
- Original location(s):
  - N/A
- New accounting location(s):
  - `modules/accounting/current_rules/customer_rules.py` (empty scaffold)
  - `modules/accounting/current_rules/sales_rules.py` (empty scaffold)
  - `modules/accounting/service.py` (Customer + Sales placeholder methods only)
- AccountingService API:
  - `get_customer_balance(customer_id: int) -> None`
  - `get_sale_outstanding(sale_id: int) -> None`
  - `get_customer_credit_balance(customer_id: int) -> None`
  - `record_customer_receipt_event(*args, **kwargs) -> None`
  - `record_sale_return_event(*args, **kwargs) -> None`
- Rewired call site(s):
  - None. No call sites rewired in this foundation card.
- Tests added/updated:
  - `tests/accounting/test_customer_sales_accounting_guardrails.py` (new)
    - `test_customer_sales_modules_do_not_import_accounting_internals`
    - `test_accounting_service_is_public_customer_sales_facade`
    - `test_customer_sales_placeholder_methods_exist`
    - `test_no_direct_accounting_internal_imports_outside_accounting_module`
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
  - Customer + Sales behavior is still scattered across repos, UI, reports, and dashboards. Call sites remain on old paths until follow-up cards migrate them.
  - Placeholder methods raise `AccountingNotImplementedError` via `_not_implemented`.
  - No template-support directory found under `modules/`; not included in tracked paths.

## CS-ACC-002: Define Customer + Sales accounting DTO/API contracts

- Migrated behavior:
  - None. Contract definition card only.
- Original location(s):
  - N/A
- New accounting location(s):
  - `modules/accounting/dto.py` (new DTOs added)
  - `modules/accounting/service.py` (new method stubs, updated return types)
  - `modules/accounting/__init__.py` (new DTO exports)
- AccountingService API:
  - `get_sale_totals(sale_id: int | str) -> SaleTotals`
  - `get_sale_financial_summary(sale_id: int | str) -> SaleFinancialSummary`
  - `get_sale_outstanding(sale_id: int | str) -> SaleOutstanding`
  - `get_sale_payment_status(sale_id: int | str) -> SalePaymentStatus`
  - `get_sale_payment_history(sale_id: int | str) -> tuple[SalePaymentRow, ...]`
  - `get_customer_credit_balance(customer_id: int) -> CustomerBalance`
  - `get_customer_open_sales(customer_id: int) -> tuple[CustomerOpenSale, ...]`
  - `get_customer_statement(customer_id: int, start_date, end_date) -> CustomerStatement`
  - `get_sale_invoice_financials(sale_id: int | str) -> SaleInvoiceFinancials`
  - `get_quotation_financials(quotation_id: int | str) -> QuotationFinancials`
  - Updated existing: `get_customer_balance` and `get_sale_outstanding` return types to DTO
- Rewired call site(s):
  - None. No call sites rewired in this contract card.
- Tests added/updated:
  - `tests/accounting/test_customer_sales_accounting_contracts.py` (new)
    - `test_customer_sales_service_contract_methods_exist`
    - `test_unmigrated_customer_sales_methods_raise_not_implemented`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Added new methods to `test_accounting_service_placeholders_raise_accounting_error`
    - Added new DTOs to `test_accounting_dtos_construct`
- Behavior change:
  - None intended.
- Notes / unresolved correctness questions:
  - All new methods raise `AccountingNotImplementedError` via `_not_implemented`.
  - DTO shapes mirror existing Vendor + Purchase DTOs.

## CS-ACC-003: Consolidate sale totals and discount summaries

- Migrated behavior:
  - Sale total reads from `sale_detailed_totals` view
  - Sale total preview calculation (UI preview math)
- Original location(s):
  - `database/repositories/sales_repo.py::get_sale_detail_summary` (inline SQL via `sale_detailed_totals`)
  - `modules/sales/controller.py::_generate_invoice_html_content` (duplicated line-item math)
  - `modules/sales/controller.py::_generate_quotation_html_content` (duplicated line-item math)
  - `modules/sales/form.py::_refresh_totals` (UI preview pattern mirrored in `preview_sale_total`)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py` (new)
    - `get_sale_totals(conn, sale_id) -> SaleTotals` — queries `sale_detailed_totals`
    - `preview_sale_total(items, order_discount) -> SaleTotals` — computes from input lines
  - `modules/accounting/dto.py` (new `SaleTotalInputLine`)
  - `modules/accounting/service.py` — `get_sale_totals` and `preview_sale_total` delegates
- AccountingService API:
  - `get_sale_totals(sale_id: int | str) -> SaleTotals` (implemented, delegates to view)
  - `preview_sale_total(items: tuple[SaleTotalInputLine, ...], order_discount: Decimal) -> SaleTotals`
- Rewired call site(s):
  - `database/repositories/sales_repo.py` — added `self.accounting`, rewired `get_sale_detail_summary` to use `self.accounting.get_sale_totals()` for `sale_detailed_totals` fields
  - `modules/sales/controller.py` — added `self.accounting`, rewired invoice and quotation total generation via `self.accounting.get_sale_totals()`
- Tests added/updated:
  - `tests/accounting/test_customer_sales_sale_totals.py` (new)
    - `test_sale_totals_match_current_view`
    - `test_sale_totals_preserve_item_and_order_discount_behavior`
    - `test_sales_repo_routes_sale_totals_through_accounting_service`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Removed `get_sale_totals` from placeholder list (now implemented)
    - Added `SaleTotalInputLine` to DTO construction test
- Behavior change:
  - None intended. Values match `sale_detailed_totals` view output.
- Notes / unresolved correctness questions:
  - `get_sale_detail_summary` now queries `sale_receivable_totals` and return/credit subqueries directly, but gets `sale_detailed_totals` fields via `AccountingService`.
  - Invoice total math replaced with service call — produces identical values since both query the same view.

## CS-ACC-004: Consolidate sale outstanding and receivable position

- Migrated behavior:
  - Sale outstanding / remaining due reads from `sale_receivable_totals` view
  - Receivable position (gross, net, paid, advance, remaining)
- Original location(s):
  - `database/repositories/sales_repo.py::get_receivable_position` (inline SQL on both views)
  - `database/repositories/sales_repo.py::get_sale_detail_summary` (receivable fields via raw SQL)
  - `database/repositories/sales_repo.py::get_sale_totals` (dict from view)
  - `modules/sales/controller.py::_fetch_sale_financials` (via detail summary)
  - `database/repositories/customer_advances_repo.py::apply_credit_to_sale` (remaining_due validation)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sale_financial_summary(conn, sale_id) -> SaleFinancialSummary` — joins both views
    - `get_sale_outstanding(conn, sale_id) -> SaleOutstanding` — delegates to financial summary
  - `modules/accounting/dto.py` — updated `SaleFinancialSummary` with `gross_total_amount` field
  - `modules/accounting/service.py` — `get_sale_financial_summary` and `get_sale_outstanding` implemented
- AccountingService API:
  - `get_sale_outstanding(sale_id: int | str) -> SaleOutstanding`
  - `get_sale_financial_summary(sale_id: int | str) -> SaleFinancialSummary`
- Rewired call site(s):
  - `database/repositories/sales_repo.py::get_receivable_position` — via `self.accounting.get_sale_financial_summary()`
  - `database/repositories/sales_repo.py::get_sale_detail_summary` — receivable fields via `self.accounting.get_sale_financial_summary()`
  - `database/repositories/sales_repo.py::get_sale_totals` — via `self.accounting.get_sale_totals()`
  - `modules/sales/controller.py::_fetch_sale_financials` — via `self.accounting.get_sale_financial_summary()`
  - `database/repositories/customer_advances_repo.py::apply_credit_to_sale` — remaining_due validation via `AccountingService(con).get_sale_outstanding()`
  - `modules/customer/controller.py` — added `self.accounting`; `_list_sales_for_customer` and `_eligible_sales_for_application` rewired via `self.accounting.list_customer_sale_summaries()`
- Tests added/updated:
  - `tests/accounting/test_customer_sales_sale_outstanding.py` (new)
    - `test_sale_outstanding_matches_receivable_view`
    - `test_sale_financial_summary_matches_sales_repo`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Removed `get_sale_outstanding` and `get_sale_financial_summary` from placeholder list
- Behavior change:
  - None intended. Values match `sale_receivable_totals` view output.
- Notes / unresolved correctness questions:
  - Customer controller bulk listing methods (`_list_sales_for_customer`, `_eligible_sales_for_application`) now route through `self.accounting.list_customer_sale_summaries()`.
  - `customer_advances_repo.apply_credit_to_sale` now validates via `AccountingService` within the same transaction.

## CS-ACC-005: Consolidate sale payment status rollups

- Migrated behavior:
  - Sale payment status calculation (`paid`/`unpaid`/`partial`)
  - Header `payment_status` refresh/recalculation
- Original location(s):
  - `database/repositories/sales_repo.py::_refresh_sale_payment_status` (inline SQL update)
  - DB triggers `trg_paid_from_sale_payments_*` and `trg_adv_applied_from_customer_*` (not removed)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sale_payment_status(conn, sale_id) -> SalePaymentStatus` — reads header + `sale_receivable_totals`
    - `recalculate_sale_payment_status(conn, sale_id) -> SalePaymentStatus` — computes status + updates header
    - `_compute_payment_status(remaining_due, paid_amount, applied_credit) -> str` — shared logic
  - `modules/accounting/service.py` — both methods delegated to current_rules
- AccountingService API:
  - `get_sale_payment_status(sale_id: int | str) -> SalePaymentStatus`
  - `recalculate_sale_payment_status(sale_id: int | str) -> SalePaymentStatus`
- Rewired call site(s):
  - `database/repositories/sales_repo.py::_refresh_sale_payment_status` — now delegates to `self.accounting.recalculate_sale_payment_status()`
  - All 4 callers of `_refresh_sale_payment_status` (create_sale, update_sale, record_return) — indirect
- Tests added/updated:
  - `tests/accounting/test_customer_sales_payment_status.py` (new)
    - `test_sale_payment_status_matches_header_rollup` — unpaid, partial, paid, credit-only
    - `test_sale_payment_status_preserves_payment_and_credit_mix`
    - `test_recalculate_sale_payment_status_preserves_sales_repo_behavior`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Removed `get_sale_payment_status` from placeholder list
- Behavior change:
  - None intended. Status logic mirrors `SalesRepo._refresh_sale_payment_status` exactly.
- Notes / unresolved correctness questions:
  - DB triggers remain intact and still fire on `sale_payments` and `customer_advances` mutations.
  - `recalculate_sale_payment_status` updates the header row directly (same as old `_refresh_sale_payment_status`).

## CS-ACC-007: Consolidate customer statement/history read model

- Migrated behavior:
  - Customer financial history assembly (sales with items, payments, returns, advances ledger, timeline, overview)
  - Customer statement (advance-based running balance)
- Original location(s):
  - `modules/customer/history.py::CustomerHistoryService` (full_history, sales_with_items, sale_payments, sale_returns, advances_ledger, timeline, overview)
  - `modules/customer/controller.py::_on_history_print` (creates CustomerHistoryService directly)
- New accounting location(s):
  - `modules/accounting/current_rules/customer_rules.py` (new)
    - `get_customer_history(conn, customer_id) -> dict` — full payload matching `CustomerHistoryService.full_history`
    - `get_customer_statement(conn, customer_id, start_date, end_date) -> CustomerStatement`
  - `modules/accounting/service.py` — `get_customer_history` and `get_customer_statement` delegated
- AccountingService API:
  - `get_customer_history(customer_id: int) -> dict`
  - `get_customer_statement(customer_id: int, start_date, end_date) -> CustomerStatement`
- Rewired call site(s):
  - `modules/customer/history.py::CustomerHistoryService` — accepts optional `accounting` kwarg; `full_history` delegates to `self._accounting.get_customer_history()` when set
  - `modules/customer/controller.py::_on_history_print` — passes `self.accounting` to `CustomerHistoryService`
  - `modules/customer/actions.py::_get_customer_history_service` — accepts optional `accounting` kwarg
- Tests added/updated:
  - `tests/accounting/test_customer_sales_customer_statement.py` (new)
    - `test_customer_statement_matches_current_history_service`
    - `test_customer_statement_preserves_timeline_order_and_event_types`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Removed `get_customer_statement` from placeholder list
- Behavior change:
  - None intended. Dict shapes, timeline order, and event kinds match `CustomerHistoryService` output exactly.
- Notes / unresolved correctness questions:
  - `CustomerHistoryService` still works standalone when `accounting` is not passed (old SQL fallback path).
  - All individual methods (`sales_with_items`, `sale_payments`, `sale_returns`, `advances_ledger`, `timeline`, `overview`) delegate through `self._accounting` when set.
  - `get_customer_statement` builds a simple running balance from the advance ledger; the full timeline-based statement is available via `get_customer_history`.

## CS-ACC-008: Rewire sales and customer display panels

- Migrated behavior:
  - Customer credit balance, sales count, open due sum, last activity dates (detail snapshot financial fields)
- Original location(s):
  - `database/repositories/customers_repo.py::get_detail_snapshot` (inline SQL for all financial subqueries)
  - `modules/customer/controller.py::_details_enrichment` (calls `self.repo.get_detail_snapshot`)
  - `modules/sales/controller.py::_sync_details_impl` (call chain already rewired in previous cards)
- New accounting location(s):
  - `modules/accounting/current_rules/customer_rules.py`
    - `get_customer_receivable_summary(conn, customer_id) -> CustomerReceivableSummary`
  - `modules/accounting/dto.py` (new `CustomerReceivableSummary` DTO)
  - `modules/accounting/service.py` — `get_customer_receivable_summary` delegated
  - `modules/accounting/__init__.py` — exported `CustomerReceivableSummary`
- AccountingService API:
  - `get_customer_receivable_summary(customer_id: int) -> CustomerReceivableSummary`
- Rewired call site(s):
  - `database/repositories/customers_repo.py` — added `self.accounting`; `get_detail_snapshot` delegates financial fields to `self.accounting.get_customer_receivable_summary()`
  - Sales and customer detail widgets (`details.py`, `model.py`) — pure rendering, no rewiring needed (data arrives via controller payloads)
- Tests added/updated:
  - `tests/accounting/test_customer_sales_display_rewiring.py` (new)
    - `test_sales_detail_payload_routes_through_accounting_service`
    - `test_customer_detail_financial_payload_routes_through_accounting_service`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Added `CustomerReceivableSummary` to DTO construction test
- Behavior change:
  - None intended. Financial field values match original `get_detail_snapshot` SQL exactly.
- Notes / unresolved correctness questions:
  - Sales detail panel (`SaleDetails`) data flows through `SalesRepo.get_sale_detail_snapshot()` → `AccountingService` via repo's `self.accounting`. Already rewired in CS-ACC-003/004.
  - Customer detail panel (`CustomerDetails`) data flows through `CustomersRepo.get_detail_snapshot()` → `AccountingService` via repo's `self.accounting`. Rewired in this card.
  - `open_due_sum` calculation uses `clearing_state IN ('posted','cleared')` matching original `get_detail_snapshot` — intentionally different from `sale_receivable_totals.paid_amount` (which uses trigger-updated cleared-only sum).

## CS-ACC-009: Consolidate sale invoice and quotation financial sourcing

- Migrated behavior:
  - Sale invoice supplementary financial context (returns, credits, net position)
  - Quotation invoice financial context
- Original location(s):
  - `modules/sales/controller.py::_generate_invoice_html_content` (inline SQL for returns, credit, payment data)
  - `modules/sales/controller.py::_generate_quotation_html_content` (inline position data)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sale_invoice_financials(conn, sale_id) -> SaleInvoiceFinancials`
    - `get_quotation_financials(conn, quotation_id) -> QuotationFinancials`
  - `modules/accounting/service.py` — both methods delegated to current_rules
- AccountingService API:
  - `get_sale_invoice_financials(sale_id: int | str) -> SaleInvoiceFinancials`
  - `get_quotation_financials(quotation_id: int | str) -> QuotationFinancials`
- Rewired call site(s):
  - `modules/sales/controller.py::_generate_invoice_html_content` — replaced returns/credit/position inline SQL with `self.accounting.get_sale_invoice_financials()`
  - `modules/sales/controller.py::_generate_quotation_html_content` — added `self.accounting.get_quotation_financials()` call
- Tests added/updated:
  - `tests/accounting/test_customer_sales_invoice_financials.py` (new)
    - `test_sale_invoice_financials_match_current_controller_context`
    - `test_quotation_invoice_financials_match_current_controller_context`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Removed `get_sale_invoice_financials` and `get_quotation_financials` from placeholder list
- Behavior change:
  - None intended. Context keys and values match original inline SQL.
- Notes / unresolved correctness questions:
  - Invoice template loading, header/doc, items, company context, and payment rows remain in the controller (template I/O and display formatting).
  - Totals already via `self.accounting.get_sale_totals()` (CS-ACC-003); receivable position via `self.accounting.get_sale_financial_summary()` (CS-ACC-004).

## CS-ACC-010: Consolidate sales, customer, dashboard, and export financial reads

- Migrated behavior:
  - Sales dashboard KPI metrics (total sales, cogs, expenses, receipts, receivables, payables)
  - Dashboard repo accounting integration
- Original location(s):
  - `database/repositories/dashboard_repo.py::summary_metrics` (inline SQL for all KPIs)
  - `database/repositories/dashboard_repo.py::open_receivables`, `open_payables` (inline SQL)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sales_dashboard_metrics(conn, date_from, date_to) -> SalesDashboardMetrics`
  - `modules/accounting/dto.py` (new `SalesDashboardMetrics`, `CustomerAgingReport`)
  - `modules/accounting/service.py` — `get_sales_dashboard_metrics` delegated
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `get_sales_dashboard_metrics(date_from: str, date_to: str) -> SalesDashboardMetrics`
- Rewired call site(s):
  - `database/repositories/dashboard_repo.py` — added `self.accounting` for future method rewiring
- Tests added/updated:
  - `tests/accounting/test_customer_sales_reports.py` (new)
    - `test_dashboard_sales_metrics_match_current_repo`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Added `SalesDashboardMetrics`, `CustomerAgingReport` to DTO construction test
- Behavior change:
  - None intended. Dashboard metrics match existing `DashboardRepo.summary_metrics` SQL.
- Notes / unresolved correctness questions:
  - `ReportingRepo` already has `self.accounting` (pre-existing). Customer aging, sales reports, and export financial reads already route through `ReportingRepo` → `AccountingService`.
  - `get_customer_aging(conn, cutoff_date)` implemented in customer_rules — uses `ReportingRepo.customer_headers_as_of_batch` via lazy import.
  - Dashboard controller `_refresh_metrics` now routes through `self.accounting.get_sales_dashboard_metrics()` with `low_stock_count` fallback via `self.repo.low_stock_count()`.
  - Report UI widgets (`CustomerAgingReports`, etc.) continue working unchanged.

## CS-ACC-011: Consolidate customer payment history read model

- Migrated behavior:
  - Sale payment history reads (by sale, by customer, latest payment)
- Original location(s):
  - `database/repositories/sale_payments_repo.py::list_by_sale` (inline SQL)
  - `database/repositories/sale_payments_repo.py::list_by_customer` (inline SQL)
  - `database/repositories/sale_payments_repo.py::get_latest_payment_for_sale` (inline SQL)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sale_payment_history(conn, sale_id) -> tuple[SalePaymentRow, ...]`
    - `get_latest_sale_payment(conn, sale_id) -> SalePaymentRow | None`
  - `modules/accounting/current_rules/customer_rules.py`
    - `get_customer_payment_history(conn, customer_id) -> tuple[SalePaymentRow, ...]`
  - `modules/accounting/service.py` — all three methods delegated to current_rules
- AccountingService API:
  - `get_sale_payment_history(sale_id: int | str) -> tuple[SalePaymentRow, ...]`
  - `get_latest_sale_payment(sale_id: int | str) -> SalePaymentRow | None`
  - `get_customer_payment_history(customer_id: int) -> tuple[SalePaymentRow, ...]`
- Rewired call site(s):
  - `database/repositories/sale_payments_repo.py::list_by_sale` — via `AccountingService(con).get_sale_payment_history(sale_id)`
  - `database/repositories/sale_payments_repo.py::list_by_customer` — via `AccountingService(con).get_customer_payment_history(customer_id)`
  - `database/repositories/sale_payments_repo.py::get_latest_payment_for_sale` — via `AccountingService(con).get_latest_sale_payment(sale_id)`
  - All indirect callers (controller invoice generation, detail snapshots, payment tab, customer history) — through the repo
- Tests added/updated:
  - `tests/accounting/test_customer_sales_payment_history.py` (new)
    - `test_sale_payment_history_matches_repo`
    - `test_latest_sale_payment_matches_repo`
    - `test_customer_payment_history_matches_repo`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Removed `get_sale_payment_history` from placeholder list
- Behavior change:
  - None intended. Row shapes, order, and field values match original `SalePaymentsRepo` SQL.
- Notes / unresolved correctness questions:
  - `SalePaymentsRepo` read methods now convert `SalePaymentRow` DTOs to plain dicts (callers use `dict()` and key access, which both work on dicts).
  - Payment write methods (`record_payment`, `record_payment_with_conn`) remain untouched.

## CS-ACC-012: Consolidate customer payment write and clearing behavior

- Migrated behavior:
  - Customer payment insert (sale_payments row, overpayment-to-credit)
  - Clearing state update (transition validation + overpayment reconciliation)
  - Clearing state reopen (admin-authorized reversal + credit reversal)
- Original location(s):
  - `database/repositories/sale_payments_repo.py::record_payment_with_conn` (inline SQL + overpayment logic)
  - `database/repositories/sale_payments_repo.py::update_clearing_state` (transition validation + overpayment)
  - `database/repositories/sale_payments_repo.py::reopen_clearing_state` (admin check + credit reversal)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `record_customer_payment_event(conn, payload) -> CustomerPaymentResult`
    - `update_customer_payment_state(conn, payment_id, *, clearing_state, ...) -> int`
    - `reopen_customer_payment_state(conn, payment_id, *, reason) -> int`
    - `_handle_overpayment(conn, ...)` — internal helper
  - `modules/accounting/dto.py` (new `CustomerPaymentPayload`, `CustomerPaymentEffect`, `CustomerPaymentResult`)
  - `modules/accounting/service.py` — all three methods delegated to current_rules
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `record_customer_payment_event(payload: CustomerPaymentPayload) -> CustomerPaymentResult`
  - `update_customer_payment_state(payment_id, *, clearing_state, cleared_date, notes) -> int`
  - `reopen_customer_payment_state(payment_id, *, reason) -> int`
- Rewired call site(s):
  - `database/repositories/sale_payments_repo.py::record_payment_with_conn` — validates via `_normalize_and_validate`, then delegates INSERT + overpayment to `AccountingService(con).record_customer_payment_event()`
  - `database/repositories/sale_payments_repo.py::update_clearing_state` — validates transitions, then delegates core UPDATE + overpayment to `AccountingService`
  - `database/repositories/sale_payments_repo.py::reopen_clearing_state` — validates admin, handles credit reversal, then delegates core UPDATE to `AccountingService`
- Tests added/updated:
  - `tests/accounting/test_customer_sales_payment_event.py` (new)
    - `test_record_customer_payment_preserves_sale_payment_row`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Added new DTO imports
- Behavior change:
  - None intended. Inserted rows, overpayment credit rows, and clearing lifecycle match original behavior.
- Notes / unresolved correctness questions:
  - Validation logic (`_normalize_and_validate`, `NORMAL_CLEARING_TRANSITIONS`) stays in `SalePaymentsRepo` for compatibility; the service does minimal validation.
  - `reopen_clearing_state` admin check and credit balance verification remain in the repo (business rule).
  - DB triggers for header rollups remain the integrity layer — the service does not duplicate trigger logic.

## CS-ACC-013: Consolidate customer advance and credit grant behavior

- Migrated behavior:
  - Customer deposit/credit grant (INSERT into customer_advances with validation)
  - Return-credit creation
  - Credit ledger reads, balance reads
- Original location(s):
  - `database/repositories/customer_advances_repo.py::grant_credit` (inline SQL + method/bank validation)
  - `database/repositories/customer_advances_repo.py::add_return_credit` (inline SQL)
  - `database/repositories/customer_advances_repo.py::get_balance` (SQL on v_customer_advance_balance)
  - `database/repositories/customer_advances_repo.py::list_ledger` (SQL on customer_advances)
- New accounting location(s):
  - `modules/accounting/current_rules/customer_rules.py`
    - `record_customer_credit_event(conn, payload) -> CustomerCreditResult`
    - `list_customer_credit_ledger(conn, customer_id) -> tuple[CustomerCreditLedgerRow, ...]`
  - `modules/accounting/dto.py` (new `CustomerCreditPayload`, `CustomerCreditResult`, `CustomerCreditLedgerRow`)
  - `modules/accounting/service.py` — all three methods delegated to current_rules
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `record_customer_credit_event(payload: CustomerCreditPayload) -> CustomerCreditResult`
  - `list_customer_credit_ledger(customer_id: int) -> tuple[CustomerCreditLedgerRow, ...]`
  - `get_customer_credit_balance(customer_id: int) -> CustomerBalance` (pre-existing, now implemented)
- Rewired call site(s):
  - `database/repositories/customer_advances_repo.py::grant_credit` — validates business rules, then delegates to `AccountingService(con).record_customer_credit_event()`
  - `database/repositories/customer_advances_repo.py::add_return_credit` — validates amount, then delegates
  - `database/repositories/customer_advances_repo.py::get_balance` — delegates to `AccountingService(con).get_customer_credit_balance()`
  - `database/repositories/customer_advances_repo.py::list_ledger` — delegates to `AccountingService(con).list_customer_credit_ledger()`
  - All indirect callers (controller credit displays, actions, history) — through the repo
- Tests added/updated:
  - `tests/accounting/test_customer_sales_customer_credit_event.py` (new)
    - `test_customer_deposit_event_matches_repo`
    - `test_customer_return_credit_event_matches_repo`
    - `test_customer_credit_ledger_matches_repo`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Added new DTO imports and construction assertions
- Behavior change:
  - None intended. Inserted rows, source types, and balance effects match original repo behavior.
- Notes / unresolved correctness questions:
  - Method/bank validation rules stay in `grant_credit()` (compatibility layer); `record_customer_credit_event` does minimal validation.
  - `apply_credit_to_sale` delegated in CS-ACC-014 (see entry below).

## CS-ACC-014: Consolidate customer credit application behavior

- Migrated behavior:
  - Customer credit application to sale (INSERT negative customer_advances row with due cap)
- Original location(s):
  - `database/repositories/customer_advances_repo.py::apply_credit_to_sale` (validation + INSERT)
- New accounting location(s):
  - `modules/accounting/current_rules/customer_rules.py`
    - `record_customer_credit_application_event(conn, payload) -> CustomerCreditApplicationResult`
  - `modules/accounting/dto.py` (new `CustomerCreditApplicationPayload`, `CustomerCreditApplicationResult`)
  - `modules/accounting/service.py` — method delegated to current_rules
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `record_customer_credit_application_event(payload: CustomerCreditApplicationPayload) -> CustomerCreditApplicationResult`
- Rewired call site(s):
  - `database/repositories/customer_advances_repo.py::apply_credit_to_sale` — validates, then delegates to `AccountingService(con).record_customer_credit_application_event()`
  - `apply_to_sale` (deprecated wrapper) — indirect
  - All callers (customer controller `_on_apply_advance`, `actions.apply_customer_advance`, sales controller `_maybe_apply_customer_credit_to_sale`) — through the repo
- Tests added/updated:
  - `tests/accounting/test_customer_sales_credit_application.py` (new)
    - `test_customer_credit_application_matches_repo`
    - `test_customer_credit_application_preserves_due_cap`
    - `test_customer_credit_application_rejects_bad_sale`
- Behavior change:
  - None intended. Inserted rows (negative amount, applied_to_sale source_type) and exception messages match original behavior.
- Notes / unresolved correctness questions:
  - DB triggers `trg_advances_no_overdraw`, `trg_customer_advances_not_exceed_remaining_due` remain the integrity layer.
  - Sale header rollup (`payment_status`, `advance_payment_applied`) is handled by DB triggers, not the service.
  - `preview_customer_credit_allocation` and `validate_customer_credit_application` not implemented — validation is inlined in the record method.

## CS-ACC-015: Consolidate sale return financial behavior

- Migrated behavior:
  - Sale return totals query
  - Sale return values query
  - Return settlement (cash refund vs customer credit split, proportional advance reinstatement)
- Original location(s):
  - `database/repositories/sales_repo.py::record_return` (settlement math + INSERTs for refund/credit)
  - `database/repositories/sales_repo.py::sale_return_totals` (inline SQL)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sale_return_totals(conn, sale_id) -> SaleReturnTotals`
    - `get_sale_return_values(conn, sale_id) -> tuple[SaleReturnValue, ...]`
    - `record_sale_return_event(conn, payload) -> SaleReturnEffect`
  - `modules/accounting/dto.py` (new `SaleReturnValue`, `SaleReturnTotals`, `SaleReturnEffect`, `SaleReturnPayload`, `SaleReturnResult`, `SaleReturnPreviewLine`, `SaleReturnPreviewPayload`)
  - `modules/accounting/service.py` — all methods delegated to current_rules
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `get_sale_return_totals(sale_id: int | str) -> SaleReturnTotals`
  - `get_sale_return_values(sale_id: int | str) -> tuple[SaleReturnValue, ...]`
  - `record_sale_return_event(payload: SaleReturnPayload) -> SaleReturnEffect`
- Rewired call site(s):
  - `database/repositories/sales_repo.py::record_return` — validates quantities, inserts inventory, captures snapshots, then delegates settlement to `self.accounting.record_sale_return_event()`
  - `database/repositories/sales_repo.py::sale_return_totals` — delegates to `self.accounting.get_sale_return_totals()`
- Tests added/updated:
  - `tests/accounting/test_customer_sales_sale_return_financials.py` (new)
    - `test_sale_return_totals_matches_repo`
    - `test_sale_return_values_matches_repo`
    - `test_sale_return_credit_settlement_matches_repo`
- Behavior change:
  - None intended. Settlement values (cash refund, credit amount, proportional advance) match original `record_return` math.
- Notes / unresolved correctness questions:
  - Inventory INSERT + snapshot trigger remain in `record_return` (tightly coupled with `next_inventory_txn_seq` and `rebuild_dirty_valuations`).
  - Service `record_sale_return_event` performs the settlement math (proportional advance, cash cap, split) and does the cash/credit INSERTs.
  - `SaleReturnPreviewLine`/`SaleReturnPreviewPayload` DTOs exist for future preview implementation but no service method wraps them yet.

## CS-ACC-016: Consolidate customer refund behavior

- Migrated behavior:
  - Customer refund reads (by customer, by sale — filtering negative payment rows)
- Original location(s):
  - Scattered across `sale_payments` queries (no centralized refund read)
- New accounting location(s):
  - `modules/accounting/current_rules/customer_rules.py`
    - `get_customer_refunds(conn, customer_id) -> tuple[CustomerRefundRow, ...]`
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sale_refunds(conn, sale_id) -> tuple[CustomerRefundRow, ...]`
  - `modules/accounting/dto.py` (new `CustomerRefundRow`)
  - `modules/accounting/service.py` — both methods delegated to current_rules
- AccountingService API:
  - `get_customer_refunds(customer_id: int) -> tuple[CustomerRefundRow, ...]`
  - `get_sale_refunds(sale_id: int | str) -> tuple[CustomerRefundRow, ...]`
- Rewired call site(s):
  - Refund reads now available through `AccountingService`; direct callers can use service methods.
  - Refund writes already go through `AccountingService` via:
    - `record_customer_payment_event` (negative amount) — CS-ACC-012
    - `record_sale_return_event` (settlement cash refund) — CS-ACC-015
    - `SalesRepo.apply_refund` — already deprecated as NotImplementedError
- Tests added/updated:
  - `tests/accounting/test_customer_sales_customer_refunds.py` (new)
    - `test_customer_refund_event_matches_current_payment_row`
- Behavior change:
  - None intended. Refund amounts (absolute values), method, and clearing_state match source `sale_payments` rows.
- Notes / unresolved correctness questions:
  - No separate `record_customer_refund_event` method — refunds are negative payments handled by `record_customer_payment_event`.
  - `CustomerRefundRow.amount` stores the absolute (positive) refund value for display convenience.

## CS-ACC-017: Consolidate bank/cash movements from customer and sales flows

- Migrated behavior:
  - Customer cash movements (cleared sale payments receipts/refunds + customer advances deposits/credits)
  - Customer payment metadata validation (method, bank account, instrument type checks)
- Original location(s):
  - `database/repositories/sale_payments_repo.py::_normalize_and_validate` (scattered method/bank validation)
  - `database/repositories/customer_advances_repo.py` (scattered metadata validation)
  - `modules/reporting/payment_reports.py` (direct bank/cash queries)
  - `database/repositories/dashboard_repo.py` (direct bank/cash queries)
- New accounting location(s):
  - `modules/accounting/current_rules/bank_rules.py`
    - `get_customer_cash_movements(conn, start_date, end_date) -> tuple[CustomerCashMovement, ...]`
  - `modules/accounting/validators.py`
    - `validate_customer_payment_metadata(conn, metadata) -> None`
    - `_validate_customer_method_requirements(metadata) -> None`
  - `modules/accounting/dto.py` (new `CustomerCashMovement`, `CustomerPaymentMetadata`)
  - `modules/accounting/service.py` — methods delegated to current_rules
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `get_customer_cash_movements(start_date, end_date) -> tuple[CustomerCashMovement, ...]`
  - `validate_customer_payment_metadata(metadata: CustomerPaymentMetadata) -> None`
- Rewired call site(s):
  - Service methods available for report/dashboard/validation call sites.
  - Existing `get_vendor_cash_movements` (line 558) used by `ReportingRepo` — customer equivalent now available.
- Tests added/updated:
  - `tests/accounting/test_customer_sales_cash_movements.py` (new)
    - `test_customer_cash_movements_match_bank_ledger_view`
    - `test_customer_payment_metadata_validation_matches_repo`
- Behavior change:
  - None intended. Cash movement types (Receipt/Refund/Customer Credit), directions, and amounts match source `sale_payments` and `customer_advances` rows.
- Notes / unresolved correctness questions:
  - `get_customer_cash_movements` UNIONs cleared sale_payments (Receipt/Refund) and deposits/return_credits from customer_advances (Customer Credit).
  - Customer payment validator covers the same methods as `VendorPaymentMetadata` but without vendor-bank fields.
  - `validate_company_bank_account_active` from bank_rules is shared between vendor and customer validators.

## CS-ACC-018: Consolidate sale inventory, COGS, margin, and profit effects

- Migrated behavior:
  - Sale inventory event (INSERT inventory_transactions for sale)
  - Sale return inventory event (INSERT inventory_transactions for sale_return with item validation)
  - Sale returnable quantities query
  - Sale COGS query from `sale_item_cogs` view
  - Sales profit summary from `sale_financial_events` view
- Original location(s):
  - `database/repositories/sales_repo.py::_insert_inventory_sale` (inline INSERT + txn_seq + rebuild)
  - `database/repositories/sales_repo.py::record_return` (inventory INSERT for sale_return)
  - `database/repositories/sales_repo.py::get_sale_totals` (returnable quantities via dict query)
  - `database/repositories/reporting_repo.py` (COGS/profit reads via `sale_item_cogs`/`sale_financial_events`)
  - `database/repositories/dashboard_repo.py` (profit/COGS reads via `sale_financial_events`)
- New accounting location(s):
  - `modules/accounting/current_rules/inventory_rules.py`
    - `record_sale_inventory_event(conn, payload) -> SaleInventoryResult`
    - `record_sale_return_inventory_event(conn, payload) -> SaleReturnInventoryResult`
    - `get_sale_returnable_quantities(conn, sale_id) -> dict[int, Decimal]`
  - `modules/accounting/current_rules/sales_rules.py`
    - `get_sale_cogs(conn, sale_id) -> SaleCogsSummary`
    - `get_sales_profit_summary(conn, start_date, end_date) -> SalesProfitSummary`
  - `modules/accounting/dto.py` (new `SaleInventoryLine`, `SaleInventoryPayload`, `SaleInventoryResult`, `SaleReturnInventoryPayload`, `SaleReturnInventoryResult`, `SaleCogsSummary`, `SalesProfitSummary`)
  - `modules/accounting/service.py` — all methods delegated to current_rules
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `record_sale_inventory_event(payload: SaleInventoryPayload) -> SaleInventoryResult`
  - `get_sale_returnable_quantities(sale_id: int | str) -> dict[int, Decimal]`
  - `record_sale_return_inventory_event(payload: SaleReturnInventoryPayload) -> SaleReturnInventoryResult`
  - `get_sale_cogs(sale_id: int | str) -> SaleCogsSummary`
  - `get_sales_profit_summary(start_date, end_date) -> SalesProfitSummary`
- Rewired call site(s):
  - Service methods available for `SalesRepo`, `ReportingRepo`, `DashboardRepo`.
  - `_check_stock_availability` remains in `SalesRepo` (inventory availability validation, not accounting calculation).
- Tests added/updated:
  - DTO construction tests in `modules/accounting/test_accounting_scaffold.py`
- Behavior change:
  - None intended. Inventory rows, returnable quantities, COGS totals, and profit values match current views and repo behavior.
- Notes / unresolved correctness questions:
  - `_insert_inventory_sale` still used directly in `SalesRepo.create_sale`/`update_sale`/`convert_quotation_to_sale` — the service method `record_sale_inventory_event` is available for future rewiring.
  - `record_return` inventory INSERT already rewired via CS-ACC-015; `record_sale_return_inventory_event` mirrors the same logic.
  - Both `sale_item_cogs` (average) and `sale_item_fifo_cogs` (FIFO) views exist — `get_sale_cogs` queries `sale_item_cogs`.

## CS-ACC-019: Consolidate quotation totals, status, and conversion behavior

- Migrated behavior:
  - Quotation conversion validation (status check: draft/sent only)
  - Quotation conversion event (mark quotation as accepted)
- Original location(s):
  - `database/repositories/sales_repo.py::convert_quotation_to_sale` (validation + status update inline)
  - `database/repositories/sales_repo.py::create_quotation` (status handling)
  - `database/repositories/sales_repo.py::update_quotation` (status handling)
- New accounting location(s):
  - `modules/accounting/current_rules/sales_rules.py`
    - `validate_quotation_conversion(conn, quotation_id) -> None`
    - `record_quotation_conversion_event(conn, payload) -> QuotationConversionResult`
  - `modules/accounting/dto.py` (new `QuotationConversionPayload`, `QuotationConversionResult`)
  - `modules/accounting/service.py` — methods delegated to current_rules
  - `modules/accounting/__init__.py` — exported new DTOs
- AccountingService API:
  - `get_quotation_financials(quotation_id: int | str) -> QuotationFinancials` (pre-existing)
  - `validate_quotation_conversion(quotation_id: int | str) -> None`
  - `record_quotation_conversion_event(payload: QuotationConversionPayload) -> QuotationConversionResult`
- Rewired call site(s):
  - Service methods available for `SalesRepo.convert_quotation_to_sale` validation step.
  - `get_quotation_financials` already used by controller invoice generation (CS-ACC-009).
- Tests added/updated:
  - `tests/accounting/test_customer_sales_quotation_behavior.py` (new)
    - `test_quotation_financials_match_current_controller_context`
    - `test_quotation_conversion_matches_current_sales_repo`
    - `test_quotation_payment_blocking_is_preserved`
- Behavior change:
  - None intended. Status validation and update match original `convert_quotation_to_sale` behavior.
- Notes / unresolved correctness questions:
  - Full quotation-to-sale conversion (sale header copy, item copy, inventory posting, stock check) remains in `SalesRepo` — tightly coupled with sale creation and `_validate_financials`/`_check_stock_availability`.
  - Service handles only the validation and status update slice; the broader conversion includes inventory and sale creation side effects that need the repo's helper methods.
