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
