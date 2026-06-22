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
  - `modules/customer/controller.py` — added `self.accounting`; bulk listing methods (ponytail: direct view query for N+1 avoidance)
- Tests added/updated:
  - `tests/accounting/test_customer_sales_sale_outstanding.py` (new)
    - `test_sale_outstanding_matches_receivable_view`
    - `test_sale_financial_summary_matches_sales_repo`
  - `modules/accounting/test_accounting_scaffold.py` (updated)
    - Removed `get_sale_outstanding` and `get_sale_financial_summary` from placeholder list
- Behavior change:
  - None intended. Values match `sale_receivable_totals` view output.
- Notes / unresolved correctness questions:
  - Customer controller bulk listing methods (`_list_sales_for_customer`, `_eligible_sales_for_application`) still query the view directly to avoid N+1; `AccountingService` is available for per-sale reads.
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
