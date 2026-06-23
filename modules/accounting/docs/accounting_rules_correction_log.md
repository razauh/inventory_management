# Accounting Rules Correction Log

## Purpose

This file is the required post-implementation log for accounting-rule correction cards in `modules/accounting/docs/accounting_rules_correction_task_cards.md`.

Use it to record what changed, what tests proved the change, and what unresolved follow-up remains after each correction card is implemented.

If older migration logs are mentioned elsewhere, treat them as background only. This file is the required correction log for these rule-fix cards.

## Rules

- Add one entry after every completed correction card.
- Use the exact card ID and problem ID in the entry heading.
- Record the focused tests that were added or updated before the production fix.
- State whether behavior changed intentionally.
- Call out data repair or backfill steps if any are needed.
- If the card was `Investigation First`, record the business-rule decision that unlocked the green step.
- Do not use this file as a brainstorming note. Record only implemented work or a clearly blocked investigation outcome.

## Entries

Copy this template for each completed card:

```markdown
## ACC-FIX-XXX: <short card title>

- Problem ID:
  - `ACC-PROB-XXX`
- Related rule IDs:
  - `<RULE-ID>`
- Card mode:
  - `Direct Fix` | `Investigation First`
- Tests added or updated:
  - `path::test_name`
- Production files changed:
  - `path`
- Behavior before:
  - <short fact>
- Behavior after:
  - <short fact>
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.
```


## ACC-FIX-010: Use real customer ID for repo overpayment conversion

- Problem ID:
  - `ACC-PROB-010`
- Related rule IDs:
  - `SAL-RULE-006`
  - `CUST-RULE-001`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_customer_sales_payment_event.py::test_sale_payments_repo_overpayment_uses_sale_customer_id`
  - `tests/accounting/test_customer_sales_payment_event.py::test_repo_overpayment_credit_posts_to_sale_customer`
- Production files changed:
  - `database/repositories/sale_payments_repo.py`
- Behavior before:
  - SalePaymentsRepo built CustomerPaymentPayload with customer_id=0, causing overpayment advances to be credited to customer 0.
- Behavior after:
  - SalePaymentsRepo queries the sales table for the real customer_id associated with the sale_id and passes it to the payment event payload.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.


## ACC-FIX-007: Cap supplier refunds to unresolved return value

- Problem ID:
  - `ACC-PROB-007`
- Related rule IDs:
  - `PUR-RULE-003`
  - `BANK-RULE-001`
  - `VND-RULE-006`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_vendor_purchase_supplier_refund.py::test_supplier_refund_rejects_amount_above_unsettled_return_value`
  - `tests/accounting/test_vendor_purchase_supplier_refund.py::test_supplier_refund_rejects_refund_without_purchase_return_value`
  - `tests/accounting/test_vendor_purchase_supplier_refund.py::test_supplier_refund_rejects_repeated_over_refund`
- Production files changed:
  - `modules/accounting/current_rules/vendor_rules.py`
  - `modules/accounting/docs/implemented_accounting_rules_reference.md`
- Behavior before:
  - record_supplier_refund_event allowed supplier refunds to be recorded for any positive amount, potentially exceeding the return value or prior settlements.
- Behavior after:
  - record_supplier_refund_event calculates the remaining refundable amount (return value minus prior refunds and credit notes) and rejects any refund exceeding this cap.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-005: Include carried return credit in vendor statement opening credit

- Problem ID:
  - `ACC-PROB-005`
- Related rule IDs:
  - `VND-RULE-001`
  - `PUR-RULE-003`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_vendor_purchase_vendor_statement.py::test_vendor_statement_opening_credit_includes_return_credit_balance`
  - `tests/accounting/test_vendor_purchase_vendor_statement.py::test_vendor_statement_opening_credit_matches_vendor_balance_basis`
- Production files changed:
  - `modules/accounting/current_rules/vendor_rules.py`
- Behavior before:
  - get_vendor_statement calculated opening credit using only 'deposit' advances, omitting 'return_credit' and 'applied_to_purchase'.
- Behavior after:
  - get_vendor_statement queries all vendor advances to calculate opening credit and opening payable, matching the vendor advance balance basis.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-011: Make customer statements honor period filters and opening balance

- Problem ID:
  - `ACC-PROB-011`
- Related rule IDs:
  - `REPORT`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_customer_sales_customer_statement.py::test_customer_statement_filters_period_and_computes_opening_balance`
  - `tests/accounting/test_customer_sales_customer_statement.py::test_customer_statement_empty_period_keeps_nonzero_opening_balance`
- Production files changed:
  - `modules/accounting/current_rules/customer_rules.py`
- Behavior before:
  - get_customer_statement read all customer advances regardless of start/end dates and hard-coded opening_balance=0.
- Behavior after:
  - get_customer_statement filters advances by period, computes the opening balance from pre-period running balances, and limits closing balance and entries to the requested period.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-012: Align customer receivable summary with cleared receivable logic

- Problem ID:
  - `ACC-PROB-012`
- Related rule IDs:
  - `SAL-RULE-006`
  - `REPORT`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_customer_sales_reports.py::test_customer_receivable_summary_ignores_posted_uncleared_payments`
  - `tests/accounting/test_customer_sales_reports.py::test_customer_receivable_summary_matches_sale_receivable_totals_remaining_due`
- Production files changed:
  - `modules/accounting/current_rules/customer_rules.py`
- Behavior before:
  - `get_customer_receivable_summary` calculated open due by subtracting payments in `('posted', 'cleared')`, thus letting posted uncleared payments reduce the due amount prematurely.
- Behavior after:
  - `get_customer_receivable_summary` sources the remaining due sum directly from the canonical `sale_receivable_totals` view which uses cleared payments only.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-015: Make bank ledger date basis explicit and consistent

- Problem ID:
  - `ACC-PROB-015`
- Related rule IDs:
  - `BANK-RULE-002`
  - `REPORT`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_vendor_purchase_cash_movements.py::test_bank_ledger_filters_on_intended_date_basis`
  - `tests/accounting/test_customer_sales_cash_movements.py::test_bank_ledger_ordering_matches_intended_date_basis`
- Production files changed:
  - `modules/accounting/current_rules/bank_rules.py`
- Behavior before:
  - `get_bank_ledger` queried `v_bank_ledger_ext` using the transaction date (`sp.date`, `pp.date`, `pr.date`), which was inconsistent with cash movements using cleared-date semantics.
- Behavior after:
  - `get_bank_ledger` queries the source payment tables directly using `cleared_date` as the date field, aligning it with cash movement cleared-date semantics.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-016: Exclude non-cash customer return credit from cash movements

- Problem ID:
  - `ACC-PROB-016`
- Related rule IDs:
  - `SAL-RULE-004`
  - `CUST-RULE-001`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_customer_sales_cash_movements.py::test_customer_cash_movements_exclude_non_cash_return_credit`
  - `tests/accounting/test_customer_sales_cash_movements.py::test_customer_deposit_credit_still_appears_in_cash_movements`
- Production files changed:
  - `modules/accounting/current_rules/bank_rules.py`
- Behavior before:
  - `get_customer_cash_movements` selected customer advances with `source_type IN ('deposit', 'return_credit')`, incorrectly treating return credits (liability) as cash inflow.
- Behavior after:
  - `get_customer_cash_movements` filters advances to `source_type = 'deposit'` only, excluding non-cash return credits.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-017: Align dashboard open payables with canonical purchase outstanding

- Problem ID:
  - `ACC-PROB-017`
- Related rule IDs:
  - `PUR-RULE-001`
  - `REPORT`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_customer_sales_reports.py::test_dashboard_open_payables_match_purchase_outstanding_after_returns`
  - `tests/accounting/test_customer_sales_reports.py::test_dashboard_open_payables_use_purchase_net_total_basis`
- Production files changed:
  - `modules/accounting/current_rules/sales_rules.py`
  - `database/repositories/dashboard_repo.py`
- Behavior before:
  - Dashboard open payables metric calculation relied on raw purchase header totals, mismatching canonical accounting purchase outstanding that is net of returns.
- Behavior after:
  - Dashboard open payables metric calculation joins `purchase_detailed_totals` and uses `COALESCE(pdt.calculated_total_amount, p.total_amount)` to align with accounting rules.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-009: Decide and enforce sale-return refund method policy

- Problem ID:
  - `ACC-PROB-009`
- Related rule IDs:
  - `BANK-RULE-001`
  - `BANK-RULE-002`
- Card mode:
  - `Investigation First` / `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_refund_method_policy_is_explicit`
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_refund_by_bank_requires_metadata_if_policy_allows_it`
- Production files changed:
  - `modules/accounting/dto.py`
  - `modules/accounting/current_rules/sales_rules.py`
- Behavior before:
  - Immediate refunds in sale returns were hard-coded as negative cash receipts with no bank metadata or validation path.
- Behavior after:
  - Enabled bank/cheque refund options by adding metadata fields to `SaleReturnPayload`, validating them using `validate_customer_payment_metadata`, and inserting them into `sale_payments` properly. Default remains Cash.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.

## ACC-FIX-001: Define one purchase outstanding presentation contract

- Problem ID:
  - `ACC-PROB-001`
- Related rule IDs:
  - `PUR-RULE-006`
  - `VND-RULE-005`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_vendor_purchase_outstanding.py::test_purchase_outstanding_api_conventions_match_documented_policy`
  - `tests/accounting/test_vendor_purchase_outstanding.py::test_purchase_outstanding_overpayment_values_are_exposed_consistently`
- Production files changed:
  - `modules/accounting/dto.py`
  - `modules/accounting/current_rules/purchase_rules.py`
- Behavior before:
  - `get_purchase_financials`, `get_purchase_outstanding`, and `get_purchase_remaining_due_header` returned inconsistent signed vs clamped outstanding amounts based on different sources (header vs payments rollup).
- Behavior after:
  - All three APIs use the same formula based on `purchases` table columns (`calculated_total_amount - paid_amount - advance_payment_applied`). They consistently return signed values, with clamped values exposed via `clamp=True` or `clamped_outstanding` DTO field.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.


## ACC-FIX-003: Make purchase returnable quantity output match stock reality

- Problem ID:
  - `ACC-PROB-003`
- Related rule IDs:
  - `PUR-RULE-003`
  - `INV-RULE-001`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_vendor_purchase_return_valuation.py::test_purchase_returnable_qty_can_exceed_stock_but_write_path_blocks`
  - `tests/accounting/test_vendor_purchase_return_valuation.py::test_purchase_returnable_quantities_expose_stock_aware_value`
- Production files changed:
  - `modules/accounting/current_rules/inventory_rules.py`
  - `modules/accounting/service.py`
  - `database/repositories/purchases_repo.py`
  - `modules/purchase/controller.py`
- Behavior before:
  - `get_purchase_returnable_quantities` only reported contractual returnable quantities, leading to misleading "Max returnable" values in the UI even when physical stock-on-hand was lower.
- Behavior after:
  - Added an optional `stock_aware: bool = False` parameter to `get_purchase_returnable_quantities`. When `True`, the returnable quantities are constrained by stock-on-hand availability. The return dialog and controller consume the stock-aware values, while checking contractual limits to verify if the purchase is fully returned.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.


## ACC-FIX-006: Preserve bank/payment metadata on auto-created vendor overpayment credit

- Problem ID:
  - `ACC-PROB-006`
- Related rule IDs:
  - `BANK-RULE-001`
  - `BANK-RULE-002`
- Card mode:
  - `Direct Fix`
- Tests added or updated:
  - `tests/accounting/test_vendor_purchase_vendor_payment_event.py::test_vendor_overpayment_credit_preserves_bank_metadata`
  - `tests/accounting/test_vendor_purchase_cash_movements.py::test_bank_ledger_keeps_account_attribution_for_vendor_overpayment_split`
- Production files changed:
  - `modules/accounting/current_rules/vendor_rules.py`
- Behavior before:
  - When a payment exceeded the outstanding purchase invoice balance, the auto-created vendor credit row in `vendor_advances` was created without propagating the payment method, company/vendor bank accounts, or instrument details.
- Behavior after:
  - Propagated all payment and bank metadata attributes from `VendorPaymentPayload` when calling `_record_vendor_deposit_credit` to create the overpayment credit row.
- Data repair / migration:
  - None.
- Follow-up questions:
  - None.
