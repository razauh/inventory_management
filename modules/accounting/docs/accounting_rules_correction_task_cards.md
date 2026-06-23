# Accounting Rules Correction Task Cards

## Purpose

This file converts every finding in `modules/accounting/docs/accounting_rules_problem_analysis.md` into a self-contained correction card.

Each card is for a future implementation turn. This file does not change code, schema, tests, or UI behavior now.

## Non-Goals

- No re-analysis of the accounting codebase
- No new findings beyond `ACC-PROB-001` through `ACC-PROB-020`
- No code or schema change in this documentation task
- No business-rule invention where the analysis marked behavior unclear
- No dependency on a missing global migration log

## Execution Rules for Future Implementers

- Treat `modules/accounting/docs/accounting_rules_problem_analysis.md` as the source of truth for scope.
- Implement one card at a time.
- Add or update focused tests first.
- Keep every change surgical. Do not fold unrelated cleanup into the same card.
- Use `modules/accounting/service.py` or approved accounting APIs for accounting behavior changes.
- Preserve current behavior first when the card says `Investigation First`.
- For `Investigation First` cards, stop after characterization plus rule decision work if the business rule is still unsettled.
- After each completed card, append an entry to `modules/accounting/docs/accounting_rules_correction_log.md`.
- If `modules/accounting/docs/accounting_consolidation_migration_log.md` is referenced elsewhere, treat it as missing background context only. Do not create or depend on it for these cards.

## Problem-to-Task Mapping

| Task Card | Problem ID | Severity | Confidence | Related Rule IDs | Correction Type | Investigation First | Notes |
|---|---|---|---|---|---|---|---|
| `ACC-FIX-001` | `ACC-PROB-001` | Medium | High | `PUR-RULE-006`, `VND-RULE-005`, `STATUS` synthesis | Consistency fix | No | Unify signed/clamped purchase due contract |
| `ACC-FIX-002` | `ACC-PROB-002` | Low | High | `REPORT` synthesis | Reporting/policy decision | Yes | Preview discount rule must be explicit |
| `ACC-FIX-003` | `ACC-PROB-003` | Medium | High | `PUR-RULE-003`, `INV-RULE-001` | Read-model consistency fix | No | Make returnable quantity stock-aware or clearly dual-valued |
| `ACC-FIX-004` | `ACC-PROB-004` | Low | High | `PUR-RULE-001` | Docs/test coverage correction | No | Docs cite nonexistent payment-history test |
| `ACC-FIX-005` | `ACC-PROB-005` | High | High | `VND-RULE-001`, `PUR-RULE-003` | Statement correctness fix | No | Opening vendor credit misses return-credit carry-forward |
| `ACC-FIX-006` | `ACC-PROB-006` | Medium | High | `BANK-RULE-001`, `BANK-RULE-002` | Metadata propagation fix | No | Vendor overpayment credit loses bank metadata |
| `ACC-FIX-007` | `ACC-PROB-007` | High | High | `PUR-RULE-003`, `BANK-RULE-001` | Write-side validation fix | No | Supplier refunds need refundable-value cap |
| `ACC-FIX-008` | `ACC-PROB-008` | Medium | High | `INV-RULE-001`, `ACC-PROB-020` | Consolidation correction | No | Sale return flow is only partly centralized |
| `ACC-FIX-009` | `ACC-PROB-009` | High | High | `BANK-RULE-001`, `BANK-RULE-002` | Refund-method policy decision | Yes | Bank/cheque refund path vs explicit cash-only rule |
| `ACC-FIX-010` | `ACC-PROB-010` | Critical | High | `SAL-RULE-006`, `CUST-RULE-001` | Data-integrity fix | No | Repo overpayment path uses `customer_id=0` |
| `ACC-FIX-011` | `ACC-PROB-011` | High | High | `REPORT` synthesis | Statement period fix | No | Date range and opening balance are ignored |
| `ACC-FIX-012` | `ACC-PROB-012` | High | High | `SAL-RULE-006`, `REPORT` synthesis | Receivable-summary fix | No | Posted uncleared receipts reduce due too early |
| `ACC-FIX-013` | `ACC-PROB-013` | Medium | High | `SAL-RULE-005`, `BANK-RULE-003` | Validation policy decision | Yes | Public credit-event validation is weaker than wrapper path |
| `ACC-FIX-014` | `ACC-PROB-014` | Medium | High | `EXP-RULE-003`, `EXP-RULE-004`, `BANK` synthesis | Architectural rule decision | Yes | Expense model has no cash/bank linkage |
| `ACC-FIX-015` | `ACC-PROB-015` | High | High | `BANK-RULE-002`, `REPORT` synthesis | Bank-date semantics fix | No | Ledger uses transaction date, not cleared date |
| `ACC-FIX-016` | `ACC-PROB-016` | High | High | `SAL-RULE-004`, `CUST-RULE-001` | Cash-movement correctness fix | No | Customer return credit appears as cash inflow |
| `ACC-FIX-017` | `ACC-PROB-017` | High | High | `PUR-RULE-001`, `REPORT` synthesis | Dashboard/report alignment fix | No | Open payables ignore purchase returns |
| `ACC-FIX-018` | `ACC-PROB-018` | Low | High | `REPORT` synthesis | Facade-scope decision | Yes | Sale invoice facade is only partial |
| `ACC-FIX-019` | `ACC-PROB-019` | Medium | High | `VND-RULE-003` | Guardrail test fix | No | Relative import bypass is not caught |
| `ACC-FIX-020` | `ACC-PROB-020` | Medium | High | `SAL-RULE-004`, `PUR-RULE-005` | Duplicate-logic consolidation fix | No | Sale return math is still duplicated outside service |

## Recommended Implementation Order

1. `ACC-FIX-010`
2. `ACC-FIX-007`
3. `ACC-FIX-005`
4. `ACC-FIX-011`
5. `ACC-FIX-012`
6. `ACC-FIX-015`
7. `ACC-FIX-016`
8. `ACC-FIX-017`
9. `ACC-FIX-009`
10. `ACC-FIX-001`
11. `ACC-FIX-003`
12. `ACC-FIX-006`
13. `ACC-FIX-008`
14. `ACC-FIX-013`
15. `ACC-FIX-014`
16. `ACC-FIX-019`
17. `ACC-FIX-020`
18. `ACC-FIX-002`
19. `ACC-FIX-004`
20. `ACC-FIX-018`

## Task Cards

### ACC-FIX-010: Use real customer ID for repo overpayment conversion

- Problem ID: `ACC-PROB-010`
- Related rule IDs: `SAL-RULE-006`, `CUST-RULE-001`
- Severity / Confidence: Critical / High
- Card mode: `Direct Fix`
- Why this card exists: `database/repositories/sale_payments_repo.py` builds `CustomerPaymentPayload(customer_id=0, ...)`, while `modules/accounting/current_rules/sales_rules.py::_handle_overpayment` posts credit rows with `payload.customer_id`.
- Files and current anchors:
  - `database/repositories/sale_payments_repo.py` — `record_payment_with_conn`
  - `modules/accounting/current_rules/sales_rules.py` — `_handle_overpayment`
  - `tests/accounting/test_customer_sales_payment_event.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_payment_event.py::test_sale_payments_repo_overpayment_uses_sale_customer_id`
  - `tests/accounting/test_customer_sales_payment_event.py::test_repo_overpayment_credit_posts_to_sale_customer`
- Red phase:
  - Reproduce cleared overpayment through `SalePaymentsRepo`, not direct service use.
  - Assert the resulting customer advance row belongs to the sale customer.
- Green phase:
  - Pass the real customer ID from repo path, or derive it safely inside the service if that keeps one source of truth.
- Refactor guardrails:
  - Do not redesign sale payment DTOs beyond what this fix needs.
  - Do not change cleared/posting-state semantics.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_payment_event.py -k overpayment`
  - `pytest tests/accounting/test_customer_sales_payment_status.py -k overpayment`
- Minimal green steps:
  - Fix the repo/service handoff.
  - Keep direct-service overpayment behavior unchanged.
- Explicit forbidden scope:
  - No customer statement changes.
  - No bank ledger changes.
  - No sale payment-status policy changes.
- Acceptance checks:
  - Repo-path cleared overpayment creates credit for the real customer.
  - No new failure in direct payment-event tests.
- Required correction log entry:
  - Append `ACC-FIX-010` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-007: Cap supplier refunds to unresolved return value

- Problem ID: `ACC-PROB-007`
- Related rule IDs: `PUR-RULE-003`, `BANK-RULE-001`
- Severity / Confidence: High / High
- Card mode: `Direct Fix`
- Why this card exists: `modules/accounting/current_rules/vendor_rules.py::record_supplier_refund_event` accepts any positive refund amount even when prior returns, refunds, and return credits do not support it.
- Files and current anchors:
  - `modules/accounting/current_rules/vendor_rules.py` — `record_supplier_refund_event`
  - `modules/accounting/docs/implemented_accounting_rules_reference.md`
  - `tests/accounting/test_vendor_purchase_supplier_refund.py`
  - `tests/accounting/test_vendor_purchase_return_event.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_supplier_refund.py::test_supplier_refund_rejects_amount_above_unsettled_return_value`
  - `tests/accounting/test_vendor_purchase_supplier_refund.py::test_supplier_refund_rejects_refund_without_purchase_return_value`
  - `tests/accounting/test_vendor_purchase_supplier_refund.py::test_supplier_refund_rejects_repeated_over_refund`
- Red phase:
  - Show refund rows can exceed unresolved refundable return value.
- Green phase:
  - Add cap or validation against the unresolved refundable amount for the purchase.
- Refactor guardrails:
  - Preserve existing metadata validation path.
  - Do not change purchase-return settlement ordering unless needed for the cap calculation.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_supplier_refund.py`
  - `pytest tests/accounting/test_vendor_purchase_return_event.py -k refund`
- Minimal green steps:
  - Compute remaining refundable value from return value minus prior refunds and prior return-credit settlement.
  - Reject excess refunds with a stable validation error.
- Explicit forbidden scope:
  - No vendor statement rewrite here.
  - No bank ledger date-basis change.
  - No broader purchase-return redesign.
- Acceptance checks:
  - Refunds cannot exceed unresolved refundable value.
  - Valid in-range refunds still post unchanged.
- Required correction log entry:
  - Append `ACC-FIX-007` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-005: Include carried return credit in vendor statement opening credit

- Problem ID: `ACC-PROB-005`
- Related rule IDs: `VND-RULE-001`, `PUR-RULE-003`
- Severity / Confidence: High / High
- Card mode: `Direct Fix`
- Why this card exists: `modules/accounting/current_rules/vendor_rules.py::get_vendor_statement` carries forward only `deposit` credit, while `return_credit` also contributes to the vendor’s actual credit balance.
- Files and current anchors:
  - `modules/accounting/current_rules/vendor_rules.py` — `get_vendor_statement`
  - `database/schema.py` — `v_vendor_advance_balance`
  - `tests/accounting/test_vendor_purchase_vendor_statement.py`
  - `tests/accounting/test_vendor_purchase_vendor_balance.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_vendor_statement.py::test_vendor_statement_opening_credit_includes_return_credit_balance`
  - `tests/accounting/test_vendor_purchase_vendor_statement.py::test_vendor_statement_opening_credit_matches_vendor_balance_basis`
- Red phase:
  - Reproduce a pre-period `return_credit` and show statement opening credit understates it.
- Green phase:
  - Use the same carried-credit basis as vendor balance unless a documented split rule is added at the same time.
- Refactor guardrails:
  - Keep statement row ordering and layout stable.
  - Do not change how in-period rows are classified.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_vendor_statement.py -k opening_credit`
  - `pytest tests/accounting/test_vendor_purchase_vendor_balance.py`
- Minimal green steps:
  - Fix opening credit query or helper.
  - Preserve deposit behavior.
- Explicit forbidden scope:
  - No change to vendor advance posting rules.
  - No supplier refund cap work here.
  - No UI statement formatting changes.
- Acceptance checks:
  - Opening credit includes unapplied pre-period `return_credit`.
  - Statement opening credit basis matches vendor balance basis.
- Required correction log entry:
  - Append `ACC-FIX-005` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-011: Make customer statements honor period filters and opening balance

- Problem ID: `ACC-PROB-011`
- Related rule IDs: `REPORT` synthesis
- Severity / Confidence: High / High
- Card mode: `Direct Fix`
- Why this card exists: `modules/accounting/current_rules/customer_rules.py::get_customer_statement` accepts `start_date` and `end_date` but reads all rows and hard-codes `opening_balance=0`.
- Files and current anchors:
  - `modules/accounting/current_rules/customer_rules.py` — `get_customer_statement`
  - `database/schema.py` — `v_customer_advance_balance`
  - `tests/accounting/test_customer_sales_customer_statement.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_customer_statement.py::test_customer_statement_filters_period_and_computes_opening_balance`
  - `tests/accounting/test_customer_sales_customer_statement.py::test_customer_statement_empty_period_keeps_nonzero_opening_balance`
- Red phase:
  - Build pre-period and in-period customer-advance activity and show dates only echo back in DTO fields.
- Green phase:
  - Filter entries to the requested window.
  - Compute opening balance from pre-period running balance.
- Refactor guardrails:
  - Keep existing statement DTO shape unless a test proves change is needed.
  - Preserve current event sign convention.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_customer_statement.py -k statement`
  - `pytest tests/accounting/test_customer_sales_reports.py -k customer`
- Minimal green steps:
  - Add period-aware query logic.
  - Preserve no-filter behavior for `None` dates.
- Explicit forbidden scope:
  - No customer receivable-summary fix here.
  - No cash-movement fix here.
  - No controller/template redesign.
- Acceptance checks:
  - Date-bounded statements exclude out-of-window rows.
  - Opening balance equals pre-period running balance.
- Required correction log entry:
  - Append `ACC-FIX-011` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-012: Align customer receivable summary with cleared receivable logic

- Problem ID: `ACC-PROB-012`
- Related rule IDs: `SAL-RULE-006`, `REPORT` synthesis
- Severity / Confidence: High / High
- Card mode: `Direct Fix`
- Why this card exists: `modules/accounting/current_rules/customer_rules.py::get_customer_receivable_summary` subtracts `sale_payments` in `('posted','cleared')` instead of using the cleared-based canonical receivable rollup.
- Files and current anchors:
  - `modules/accounting/current_rules/customer_rules.py` — `get_customer_receivable_summary`
  - `database/schema.py` — `sale_receivable_totals`
  - `database/repositories/customers_repo.py`
  - `tests/accounting/test_customer_sales_reports.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_reports.py::test_customer_receivable_summary_ignores_posted_uncleared_payments`
  - `tests/accounting/test_customer_sales_reports.py::test_customer_receivable_summary_matches_sale_receivable_totals_remaining_due`
- Red phase:
  - Reproduce one posted-but-uncleared receipt and show summary due drops too early.
- Green phase:
  - Source `open_due_sum` from canonical cleared-based totals, or add a second explicit metric if the product truly needs posted-inclusive reporting.
- Refactor guardrails:
  - Keep summary DTO/API stable if possible.
  - Do not alter sale payment state machine behavior.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_reports.py -k receivable`
  - `pytest tests/accounting/test_customer_sales_payment_status.py -k cleared`
- Minimal green steps:
  - Replace posted-inclusive math with canonical receivable basis.
  - Update any dependent test expectations only where this rule is directly consumed.
- Explicit forbidden scope:
  - No statement-period fix here.
  - No sale status-trigger changes.
  - No dashboard payable changes.
- Acceptance checks:
  - Posted uncleared receipts do not reduce receivable summary due.
  - Summary agrees with cleared receivable rollups.
- Required correction log entry:
  - Append `ACC-FIX-012` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-015: Make bank ledger date basis explicit and consistent

- Problem ID: `ACC-PROB-015`
- Related rule IDs: `BANK-RULE-002`, `REPORT` synthesis
- Severity / Confidence: High / High
- Card mode: `Direct Fix`
- Why this card exists: `modules/accounting/current_rules/bank_rules.py::get_bank_ledger` filters `v_bank_ledger_ext` by source transaction date, while related cleared-cash readers operate on cleared semantics.
- Files and current anchors:
  - `modules/accounting/current_rules/bank_rules.py` — `get_bank_ledger`, `get_vendor_cash_movements`, `get_customer_cash_movements`
  - `database/schema.py` — `v_bank_ledger_ext`
  - `tests/accounting/test_vendor_purchase_cash_movements.py`
  - `tests/accounting/test_customer_sales_cash_movements.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_cash_movements.py::test_bank_ledger_filters_on_intended_date_basis`
  - `tests/accounting/test_customer_sales_cash_movements.py::test_bank_ledger_ordering_matches_intended_date_basis`
- Red phase:
  - Create delayed-clearing activity with entry date A and cleared date B and show wrong period inclusion.
- Green phase:
  - Pick one explicit date basis for bank ledger and make code plus docs match it.
- Refactor guardrails:
  - Keep row amounts and account attribution unchanged.
  - Do not mix this card with metadata-propagation work from `ACC-FIX-006`.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_cash_movements.py -k bank_ledger`
  - `pytest tests/accounting/test_customer_sales_cash_movements.py -k bank_ledger`
- Minimal green steps:
  - Update query/filter basis and any helper naming needed to make semantics clear.
  - Add a short doc note if the chosen basis must stay non-obvious.
- Explicit forbidden scope:
  - No sale refund-method policy change.
  - No customer return-credit exclusion change.
  - No dashboard metric change.
- Acceptance checks:
  - Delayed-clearing entries land in the intended reporting window.
  - Ledger date basis is explicit in tests.
- Required correction log entry:
  - Append `ACC-FIX-015` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-016: Exclude non-cash customer return credit from cash movements

- Problem ID: `ACC-PROB-016`
- Related rule IDs: `SAL-RULE-004`, `CUST-RULE-001`
- Severity / Confidence: High / High
- Card mode: `Direct Fix`
- Why this card exists: `modules/accounting/current_rules/bank_rules.py::get_customer_cash_movements` includes `customer_advances.source_type='return_credit'`, even though return credit is a liability entry, not necessarily cash.
- Files and current anchors:
  - `modules/accounting/current_rules/bank_rules.py` — `get_customer_cash_movements`
  - `tests/accounting/test_customer_sales_cash_movements.py`
  - `tests/accounting/test_customer_sales_customer_credit_event.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_cash_movements.py::test_customer_cash_movements_exclude_non_cash_return_credit`
  - `tests/accounting/test_customer_sales_cash_movements.py::test_customer_deposit_credit_still_appears_in_cash_movements`
- Red phase:
  - Show `return_credit` rows surface as `Customer Credit` cash inflow.
- Green phase:
  - Exclude non-cash return-credit rows from customer cash-movement view unless a card later introduces true cash-linked return-credit semantics.
- Refactor guardrails:
  - Preserve deposit-credit visibility.
  - Keep customer credit ledger behavior unchanged.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_cash_movements.py -k return_credit`
  - `pytest tests/accounting/test_customer_sales_customer_credit_event.py -k return_credit`
- Minimal green steps:
  - Narrow the cash-movement query.
  - Update labels only if needed by the narrowed query.
- Explicit forbidden scope:
  - No sale return settlement redesign.
  - No customer statement fix here.
  - No vendor cash-movement changes.
- Acceptance checks:
  - Customer return credit no longer appears as cash inflow.
  - Deposit-based customer credit behavior stays intact.
- Required correction log entry:
  - Append `ACC-FIX-016` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-017: Align dashboard open payables with canonical purchase outstanding

- Problem ID: `ACC-PROB-017`
- Related rule IDs: `PUR-RULE-001`, `REPORT` synthesis
- Severity / Confidence: High / High
- Card mode: `Direct Fix`
- Why this card exists: dashboard open-payable math uses purchase header totals, while accounting purchase outstanding uses `purchase_detailed_totals.calculated_total_amount`, which is net of returns.
- Files and current anchors:
  - `modules/accounting/current_rules/sales_rules.py` — `get_sales_dashboard_metrics`
  - `database/repositories/dashboard_repo.py` — `summary_metrics`, `open_payables`
  - `modules/accounting/current_rules/purchase_rules.py` — canonical purchase outstanding read path
  - `tests/accounting/test_customer_sales_reports.py`
  - `tests/accounting/test_vendor_purchase_outstanding.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_reports.py::test_dashboard_open_payables_match_purchase_outstanding_after_returns`
  - `tests/accounting/test_customer_sales_reports.py::test_dashboard_open_payables_use_purchase_net_total_basis`
- Red phase:
  - Create purchase returns and show dashboard AP differs from purchase outstanding.
- Green phase:
  - Route dashboard payable math through the same canonical purchase-total basis.
- Refactor guardrails:
  - Keep unrelated dashboard metrics unchanged.
  - Avoid mixing in bank or expense report work.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_reports.py -k payables`
  - `pytest tests/accounting/test_vendor_purchase_outstanding.py -k outstanding`
- Minimal green steps:
  - Replace header-total formula with canonical net-purchase formula in dashboard readers.
  - Keep public dashboard method signatures stable.
- Explicit forbidden scope:
  - No purchase outstanding sign-policy rewrite here.
  - No expense-dashboard redesign.
  - No sales profit/COGS changes.
- Acceptance checks:
  - Dashboard open payables match canonical purchase outstanding after returns.
  - Header total mismatches no longer overstate AP dashboard values.
- Required correction log entry:
  - Append `ACC-FIX-017` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-009: Decide and enforce sale-return refund method policy

- Problem ID: `ACC-PROB-009`
- Related rule IDs: `BANK-RULE-001`, `BANK-RULE-002`
- Severity / Confidence: High / High
- Card mode: `Investigation First`
- Why this card exists: `modules/accounting/current_rules/sales_rules.py::record_sale_return_event` hard-codes immediate refunds as negative cash receipts with no bank metadata path.
- Files and current anchors:
  - `modules/accounting/current_rules/sales_rules.py` — `record_sale_return_event`
  - `tests/accounting/test_customer_sales_sale_return_financials.py`
  - `tests/accounting/test_customer_sales_cash_movements.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_refund_method_policy_is_explicit`
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_refund_by_bank_requires_metadata_if_policy_allows_it`
- Red phase:
  - Characterize current cash-only behavior.
  - Add one failing policy test that expresses the chosen business rule.
- Green phase:
  - If product approves bank/cheque refunds, add refund metadata fields and enforce them.
  - If product confirms cash-only refunds, lock that rule in docs, validation, and tests.
- Refactor guardrails:
  - Keep refund amount math unchanged unless a failing test proves coupling.
  - Do not fold `ACC-FIX-016` into this card.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_sale_return_financials.py -k refund_method`
  - `pytest tests/accounting/test_customer_sales_cash_movements.py -k refund`
- Minimal green steps:
  - Stop after characterization plus explicit rule decision if policy is still unsettled.
  - Once decision exists, implement the smallest path that makes refund method explicit.
- Explicit forbidden scope:
  - No customer credit-event validation rewrite.
  - No bank ledger date-basis work.
  - No sale return inventory centralization.
- Acceptance checks:
  - Refund-method policy is explicit in tests.
  - If non-cash refunds are allowed, bank metadata is represented and validated.
  - If only cash refunds are allowed, code and docs reject other methods clearly.
- Required correction log entry:
  - Append `ACC-FIX-009` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-001: Define one purchase outstanding presentation contract

- Problem ID: `ACC-PROB-001`
- Related rule IDs: `PUR-RULE-006`, `VND-RULE-005`, `STATUS` synthesis
- Severity / Confidence: Medium / High
- Card mode: `Direct Fix`
- Why this card exists: `get_purchase_financials`, `get_purchase_outstanding`, and `get_purchase_remaining_due_header` expose conflicting signed vs clamped due values for the same purchase.
- Files and current anchors:
  - `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_financials`, `get_purchase_outstanding`
  - `modules/accounting/service.py` — `get_purchase_remaining_due_header`
  - `tests/accounting/test_vendor_purchase_outstanding.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_outstanding.py::test_purchase_outstanding_api_conventions_match_documented_policy`
  - `tests/accounting/test_vendor_purchase_outstanding.py::test_purchase_outstanding_overpayment_values_are_exposed_consistently`
- Red phase:
  - Reproduce an overpaid purchase and show all three APIs disagree.
- Green phase:
  - Pick one documented contract:
    - signed plus explicit clamped value, or
    - one shared convention across all public readers.
- Refactor guardrails:
  - Keep purchase-status semantics stable.
  - Do not change vendor balance logic unless the test proves a direct dependency.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_outstanding.py`
  - `pytest tests/accounting/test_vendor_purchase_payment_status.py -k purchase`
- Minimal green steps:
  - Make all public purchase-due readers agree by contract.
  - Update service naming or DTO fields only if needed to avoid ambiguity.
- Explicit forbidden scope:
  - No dashboard payable fix here.
  - No vendor statement fix here.
  - No payment-history docs cleanup.
- Acceptance checks:
  - Same overpayment scenario yields one documented due convention across public APIs.
  - Tests make signed/clamped behavior explicit.
- Required correction log entry:
  - Append `ACC-FIX-001` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-003: Make purchase returnable quantity output match stock reality

- Problem ID: `ACC-PROB-003`
- Related rule IDs: `PUR-RULE-003`, `INV-RULE-001`
- Severity / Confidence: Medium / High
- Card mode: `Direct Fix`
- Why this card exists: `get_purchase_returnable_quantities` shows contractual returnable quantity only, while the write path blocks returns above current stock-on-hand.
- Files and current anchors:
  - `modules/accounting/current_rules/inventory_rules.py` — `get_purchase_returnable_quantities`
  - `modules/accounting/current_rules/purchase_rules.py` — `record_purchase_return_event`
  - `modules/purchase/return_form.py`
  - `tests/accounting/test_vendor_purchase_return_valuation.py`
  - `tests/accounting/test_vendor_purchase_return_event.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_return_valuation.py::test_purchase_returnable_qty_can_exceed_stock_but_write_path_blocks`
  - `tests/accounting/test_vendor_purchase_return_valuation.py::test_purchase_returnable_quantities_expose_stock_aware_value`
- Red phase:
  - Reproduce stock depletion after purchase and show UI/helper returnable quantity exceeds stock-aware reality.
- Green phase:
  - Expose both contractual and stock-available values, or rename/label the helper so consumers cannot mistake it for stock-aware availability.
- Refactor guardrails:
  - Preserve actual write-path stock validation.
  - Do not change purchase-return settlement math.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_return_valuation.py -k returnable`
  - `pytest tests/accounting/test_vendor_purchase_return_event.py -k stock`
- Minimal green steps:
  - Add the smallest stock-aware read-model support needed by current consumer path.
  - Update `modules/purchase/return_form.py` only if required by the new contract.
- Explicit forbidden scope:
  - No inventory trigger redesign.
  - No sale return helper changes.
  - No purchase invoice preview changes.
- Acceptance checks:
  - Read path no longer misleads users about physically returnable quantity.
  - Write path still blocks invalid stock quantities.
- Required correction log entry:
  - Append `ACC-FIX-003` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-006: Preserve bank/payment metadata on auto-created vendor overpayment credit

- Problem ID: `ACC-PROB-006`
- Related rule IDs: `BANK-RULE-001`, `BANK-RULE-002`
- Severity / Confidence: Medium / High
- Card mode: `Direct Fix`
- Why this card exists: `_record_vendor_deposit_credit` creates the excess-credit row without payment method, account, instrument, or clearing metadata.
- Files and current anchors:
  - `modules/accounting/current_rules/vendor_rules.py` — `_record_vendor_deposit_credit`, `record_vendor_payment_event`
  - `database/schema.py` — `vendor_advances`
  - `modules/accounting/current_rules/bank_rules.py` — `get_bank_ledger`
  - `tests/accounting/test_vendor_purchase_vendor_payment_event.py`
  - `tests/accounting/test_vendor_purchase_cash_movements.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_vendor_payment_event.py::test_vendor_overpayment_credit_preserves_bank_metadata`
  - `tests/accounting/test_vendor_purchase_cash_movements.py::test_bank_ledger_keeps_account_attribution_for_vendor_overpayment_split`
- Red phase:
  - Record bank-method overpayment and show excess-credit row loses attribution.
- Green phase:
  - Propagate enough metadata to reconcile the full outgoing cash movement across both resulting rows.
- Refactor guardrails:
  - Preserve overpayment amount split.
  - Do not change vendor credit-balance math.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_vendor_payment_event.py -k overpayment`
  - `pytest tests/accounting/test_vendor_purchase_cash_movements.py -k overpayment`
- Minimal green steps:
  - Add metadata propagation to the auto-created credit path.
  - Keep old paths working for cash payments.
- Explicit forbidden scope:
  - No bank ledger date-basis fix here.
  - No vendor statement fix here.
  - No validator expansion beyond metadata propagation needs.
- Acceptance checks:
  - Auto-created excess-credit rows retain account/payment attribution.
  - Bank movement reports can reconcile the full payment amount.
- Required correction log entry:
  - Append `ACC-FIX-006` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-008: Finish sale-return ownership boundaries

- Problem ID: `ACC-PROB-008`
- Related rule IDs: `INV-RULE-001`, `ACC-PROB-020`
- Severity / Confidence: Medium / High
- Card mode: `Direct Fix`
- Why this card exists: docs describe a consolidated sale-return rule, but inventory validation/posting still lives partly in `database/repositories/sales_repo.py`.
- Files and current anchors:
  - `modules/accounting/current_rules/sales_rules.py` — `record_sale_return_event`
  - `database/repositories/sales_repo.py`
  - `tests/accounting/test_customer_sales_sale_return_financials.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_service_owns_documented_responsibilities`
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_repo_service_boundary_is_explicit`
- Red phase:
  - Lock current split behavior in characterization tests and identify the single responsibility gap to close.
- Green phase:
  - Move the missing sale-return responsibility into the accounting service or narrow the docs so the boundary is explicit.
- Refactor guardrails:
  - Keep return settlement amounts unchanged.
  - Avoid mixing with UI preview math cleanup from `ACC-FIX-020` unless required.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_sale_return_financials.py`
  - `pytest tests/accounting/test_customer_sales_display_rewiring.py -k return`
- Minimal green steps:
  - Make one source of truth for the documented ownership boundary.
  - Update docs/tests together if ownership remains intentionally split.
- Explicit forbidden scope:
  - No refund-method policy work here.
  - No bank/cash reporting change.
  - No inventory valuation redesign.
- Acceptance checks:
  - Tests state exactly which layer owns sale-return responsibilities.
  - Service/docs boundary is no longer misleading.
- Required correction log entry:
  - Append `ACC-FIX-008` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-013: Make customer credit-event validation authoritative at service level

- Problem ID: `ACC-PROB-013`
- Related rule IDs: `SAL-RULE-005`, `BANK-RULE-003`
- Severity / Confidence: Medium / High
- Card mode: `Investigation First`
- Why this card exists: `record_customer_credit_event` accepts weaker non-cash metadata than the repo wrapper path, so direct service use and wrapped use disagree.
- Files and current anchors:
  - `modules/accounting/current_rules/customer_rules.py` — `record_customer_credit_event`
  - `modules/accounting/validators.py` — `validate_customer_payment_metadata`
  - `database/repositories/customer_advances_repo.py`
  - `tests/accounting/test_customer_sales_customer_credit_event.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_customer_credit_event.py::test_customer_credit_event_validation_matches_receipt_rules`
  - `tests/accounting/test_customer_sales_customer_credit_event.py::test_non_cash_customer_credit_requires_reference_and_bank_if_policy_requires_it`
- Red phase:
  - Characterize the current mismatch between direct service and repo wrapper.
  - Add one failing policy test for the chosen non-cash metadata rule.
- Green phase:
  - If product wants parity, move the strongest validator path into the public service.
  - If product wants looser customer-credit rules, document the explicit exception and update wrappers/tests to match.
- Refactor guardrails:
  - Keep existing happy-path deposit and return-credit behavior.
  - Do not change customer cash-movement queries in this card.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_customer_credit_event.py -k validation`
  - `pytest tests/accounting/test_customer_sales_payment_event.py -k metadata`
- Minimal green steps:
  - Stop after characterization if policy is unsettled.
  - Once rule exists, enforce it in exactly one authoritative validation layer.
- Explicit forbidden scope:
  - No sale overpayment bug fix here.
  - No statement-period work.
  - No expense model work.
- Acceptance checks:
  - Direct service and wrapped write paths enforce the same documented rule.
  - Non-cash metadata expectations are explicit in tests.
- Required correction log entry:
  - Append `ACC-FIX-013` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-014: Decide whether the expense model must link to cash/bank events

- Problem ID: `ACC-PROB-014`
- Related rule IDs: `EXP-RULE-003`, `EXP-RULE-004`, `BANK` synthesis
- Severity / Confidence: Medium / High
- Card mode: `Investigation First`
- Why this card exists: expenses move P&L and dashboard totals with no payment-status, vendor, payable, or bank linkage model at all.
- Files and current anchors:
  - `database/schema.py` — `expenses`
  - `modules/accounting/current_rules/expense_rules.py`
  - `modules/accounting/docs/expenses/vendor_purchase_overlap_risk.md`
  - `tests/accounting/test_expense_write_events.py`
  - `tests/accounting/test_expense_dashboard_totals.py`
  - `tests/accounting/test_expense_profit_loss_summary.py`
- Tests to write first:
  - `tests/accounting/test_expense_write_events.py::test_expense_model_no_cash_link_is_documented_behavior`
  - `tests/accounting/test_expense_dashboard_totals.py::test_expense_reporting_policy_matches_documented_no_bank_link_decision`
- Red phase:
  - Characterize current direct-write expense behavior and its immediate effect on reporting.
  - Add a failing policy test that encodes the chosen product decision.
- Green phase:
  - If the simple no-bank-link model is accepted, document and lock it explicitly.
  - If not accepted, create a follow-up implementation card that introduces the smallest approved linkage model.
- Refactor guardrails:
  - Do not invent a full AP or expense-ledger subsystem inside this card.
  - Do not change expense CRUD unless the rule decision requires it.
- Focused pytest commands:
  - `pytest tests/accounting/test_expense_write_events.py`
  - `pytest tests/accounting/test_expense_dashboard_totals.py`
  - `pytest tests/accounting/test_expense_profit_loss_summary.py`
- Minimal green steps:
  - This card may end as a documented accepted constraint instead of a code change.
  - If the rule is not accepted, log the decision and create the follow-up card rather than guessing architecture.
- Explicit forbidden scope:
  - No vendor purchase overlap cleanup unless a follow-up card explicitly asks for it.
  - No schema redesign by default.
  - No external ERP/accounting integration.
- Acceptance checks:
  - Product decision on expense cash/bank linkage is explicit.
  - Tests and docs reflect that decision without inventing speculative architecture.
- Required correction log entry:
  - Append `ACC-FIX-014` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-019: Tighten guardrails to catch relative imports of accounting internals

- Problem ID: `ACC-PROB-019`
- Related rule IDs: `VND-RULE-003`
- Severity / Confidence: Medium / High
- Card mode: `Direct Fix`
- Why this card exists: existing guardrail coverage misses a direct fallback relative import of accounting internals in `modules/vendor/controller.py`.
- Files and current anchors:
  - `modules/vendor/controller.py`
  - `tests/accounting/test_vendor_purchase_accounting_guardrails.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_accounting_guardrails.py::test_guardrails_reject_relative_imports_of_accounting_internals`
  - `tests/accounting/test_vendor_purchase_accounting_guardrails.py::test_guardrails_scan_fallback_vendor_controller_import_path`
- Red phase:
  - Show current guardrail scan passes even when a relative accounting-internal import exists.
- Green phase:
  - Expand the import scanner so absolute and relative internal-import bypasses are both caught.
- Refactor guardrails:
  - Keep production behavior unchanged if only the test needs fixing.
  - If production import cleanup is needed, make the smallest possible change.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_accounting_guardrails.py`
- Minimal green steps:
  - Update the guardrail test helper.
  - Only touch `modules/vendor/controller.py` if the test confirms a real forbidden import remains.
- Explicit forbidden scope:
  - No broad guardrail rewrite across unrelated modules.
  - No accounting behavior change.
  - No customer/sales import cleanup in this card.
- Acceptance checks:
  - Guardrail tests fail on relative imports of accounting internals.
  - Existing allowed public-facade imports still pass.
- Required correction log entry:
  - Append `ACC-FIX-019` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-020: Remove duplicated sale-return math outside `AccountingService`

- Problem ID: `ACC-PROB-020`
- Related rule IDs: `SAL-RULE-004`, `PUR-RULE-005`
- Severity / Confidence: Medium / High
- Card mode: `Direct Fix`
- Why this card exists: return value and returnable-quantity math still live in `modules/sales/return_form.py`, `database/repositories/sales_returns_helpers.py`, and `database/repositories/sales_repo.py`.
- Files and current anchors:
  - `modules/sales/return_form.py`
  - `database/repositories/sales_returns_helpers.py`
  - `database/repositories/sales_repo.py`
  - `modules/accounting/current_rules/sales_rules.py`
  - `tests/accounting/test_customer_sales_sale_return_financials.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_helpers_match_accounting_service_math`
  - `tests/accounting/test_customer_sales_sale_return_financials.py::test_sale_return_preview_and_write_paths_share_one_formula`
- Red phase:
  - Lock current helper/UI/repo formulas beside service outputs and show drift risk.
- Green phase:
  - Move shared math into one accounting-owned helper or API and rewire duplicate callers.
- Refactor guardrails:
  - Preserve actual return settlement outputs.
  - Avoid folding ownership-boundary work from `ACC-FIX-008` unless directly required.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_sale_return_financials.py -k helper`
  - `pytest tests/accounting/test_customer_sales_display_rewiring.py -k return`
- Minimal green steps:
  - Reuse one formula source for preview and write paths.
  - Remove only the duplicate math made obsolete by this card.
- Explicit forbidden scope:
  - No sale refund-method policy work.
  - No unrelated sales UI redesign.
  - No inventory trigger rewrite.
- Acceptance checks:
  - UI preview, helper path, and service/write path use one documented formula source.
  - Duplicate math removed only where the new source is proven equivalent.
- Required correction log entry:
  - Append `ACC-FIX-020` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-002: Decide whether purchase invoice preview must show order discount

- Problem ID: `ACC-PROB-002`
- Related rule IDs: `REPORT` synthesis
- Severity / Confidence: Low / High
- Card mode: `Investigation First`
- Why this card exists: `get_purchase_invoice_financials` deliberately zeroes out preview discount totals while invoice detail context keeps the real discount.
- Files and current anchors:
  - `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_invoice_financials`
  - `widgets/invoice_preview.py`
  - `resources/templates/invoices/purchase_invoice.html`
  - `tests/accounting/test_vendor_purchase_invoice_financials.py`
  - `modules/accounting/docs/purchase_vendor/vendor_purchase_migration_verification_audit.md`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_invoice_financials.py::test_purchase_invoice_preview_discount_policy_is_explicit`
  - `tests/accounting/test_vendor_purchase_invoice_financials.py::test_purchase_invoice_preview_totals_match_documented_discount_rule`
- Red phase:
  - Characterize the current subtotal-only preview output when order discount exists.
  - Add a failing policy test for the chosen preview rule.
- Green phase:
  - If preview should match canonical totals, remove the fallback.
  - If preview should stay subtotal-only, document and lock the exception clearly.
- Refactor guardrails:
  - Do not redesign invoice templates.
  - Keep detail-context totals unchanged unless product decides otherwise.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_invoice_financials.py -k preview`
- Minimal green steps:
  - Stop after characterization if rule is not approved.
  - Once approved, implement the smallest preview-context change or explicit exception.
- Explicit forbidden scope:
  - No purchase due-contract fix here.
  - No docs sweep outside preview rule references.
  - No sales invoice work.
- Acceptance checks:
  - Discount behavior in preview is explicit in tests and docs.
  - Preview consumers no longer rely on an undocumented exception.
- Required correction log entry:
  - Append `ACC-FIX-002` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-004: Fix purchase payment-history documentation and direct test coverage

- Problem ID: `ACC-PROB-004`
- Related rule IDs: `PUR-RULE-001`
- Severity / Confidence: Low / High
- Card mode: `Direct Fix`
- Why this card exists: docs claim there is a dedicated purchase payment-history test file, but only summary tests exist today.
- Files and current anchors:
  - `modules/accounting/docs/implemented_accounting_rules_reference.md`
  - `modules/accounting/docs/implemented_accounting_rules_explained.md`
  - `tests/accounting/test_vendor_purchase_payment_summary.py`
- Tests to write first:
  - `tests/accounting/test_vendor_purchase_payment_summary.py::test_purchase_payment_history_order_and_metadata`
- Red phase:
  - Show the docs point at a nonexistent `test_vendor_purchase_payment_history.py`.
- Green phase:
  - Either correct the docs to the real coverage file, or add a small dedicated history test and update docs to match the true target.
- Refactor guardrails:
  - Prefer the smallest fix. If doc correction alone is enough, do not create a new test file without reason.
- Focused pytest commands:
  - `pytest tests/accounting/test_vendor_purchase_payment_summary.py -k history`
- Minimal green steps:
  - Align docs with actual coverage.
  - Add one direct history-ordering test if current coverage is too indirect.
- Explicit forbidden scope:
  - No purchase payment-status changes.
  - No invoice preview work.
  - No broader docs cleanup.
- Acceptance checks:
  - Docs no longer cite nonexistent test files.
  - Payment-history coverage target is accurate and explicit.
- Required correction log entry:
  - Append `ACC-FIX-004` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

### ACC-FIX-018: Decide whether sale invoice facade should become complete or stay partial

- Problem ID: `ACC-PROB-018`
- Related rule IDs: `REPORT` synthesis
- Severity / Confidence: Low / High
- Card mode: `Investigation First`
- Why this card exists: `get_sale_invoice_financials` returns partial settlement context, while controller/template consumers still assemble totals, company context, and payments elsewhere.
- Files and current anchors:
  - `modules/accounting/current_rules/sales_rules.py` — `get_sale_invoice_financials`
  - `modules/sales/controller.py`
  - `resources/templates/invoices/sale_invoice.html`
  - `tests/accounting/test_customer_sales_invoice_financials.py`
- Tests to write first:
  - `tests/accounting/test_customer_sales_invoice_financials.py::test_sale_invoice_facade_scope_is_explicit`
  - `tests/accounting/test_customer_sales_invoice_financials.py::test_sale_invoice_service_and_controller_contexts_match_documented_contract`
- Red phase:
  - Characterize the partial facade and the controller-assembled extra context.
  - Add a failing contract test for the chosen facade scope.
- Green phase:
  - Either expand the facade into the complete supported contract, or document and lock it as intentionally partial.
- Refactor guardrails:
  - Do not rebuild invoice templates unless the chosen contract requires it.
  - Keep sale total math untouched unless the contract gap exposes a real defect.
- Focused pytest commands:
  - `pytest tests/accounting/test_customer_sales_invoice_financials.py`
  - `pytest tests/accounting/test_customer_sales_display_rewiring.py -k invoice`
- Minimal green steps:
  - Stop after characterization if facade scope is still undecided.
  - Once scope is approved, make one contract source of truth.
- Explicit forbidden scope:
  - No customer statement or receivable work.
  - No purchase invoice preview work.
  - No quotation conversion changes.
- Acceptance checks:
  - Facade scope is explicit in tests and docs.
  - New consumers cannot assume undocumented invoice fields.
- Required correction log entry:
  - Append `ACC-FIX-018` entry to `modules/accounting/docs/accounting_rules_correction_log.md`.

## Cross-Cutting Test Strategy

- Add failing or characterization tests in the smallest existing accounting test file that already covers the area.
- Prefer repo-path tests over direct-service-only tests when the bug is in a wrapper handoff.
- For report/read-model fixes, add one scenario test that reproduces the divergence and one parity test against the canonical accounting source.
- For `Investigation First` cards, add:
  - one characterization test for current behavior
  - one explicit policy test name for the intended rule
- Keep pytest targets focused to the touched area plus one nearby guardrail file when the fix changes a shared contract.

## Suggested Fix Phases

1. Critical data-integrity path
   - `ACC-FIX-010`
2. High-severity write and statement correctness
   - `ACC-FIX-007`
   - `ACC-FIX-005`
   - `ACC-FIX-011`
   - `ACC-FIX-012`
3. High-severity bank/report correctness
   - `ACC-FIX-015`
   - `ACC-FIX-016`
   - `ACC-FIX-017`
4. Policy-sensitive high-risk work
   - `ACC-FIX-009`
   - `ACC-FIX-013`
   - `ACC-FIX-014`
5. Medium consistency and consolidation cleanup
   - `ACC-FIX-001`
   - `ACC-FIX-003`
   - `ACC-FIX-006`
   - `ACC-FIX-008`
   - `ACC-FIX-019`
   - `ACC-FIX-020`
6. Low-risk docs/template completeness
   - `ACC-FIX-002`
   - `ACC-FIX-004`
   - `ACC-FIX-018`

## Global Acceptance Criteria

- All `ACC-PROB-001` through `ACC-PROB-020` findings map to exactly one correction card.
- Every card names target files, test files, failing test names, and focused pytest commands.
- `Investigation First` cards are clearly labeled and do not invent final business rules.
- Every card points to `modules/accounting/docs/accounting_rules_correction_log.md`.
- Recommended order is explicit and starts with the repo-path overpayment bug.
- No code, schema, UI, or test execution is performed by this documentation task.

## Final Confirmation

- Created one correction-card document for all 20 findings.
- Created one reusable correction-log template.
- Did not create or depend on `modules/accounting/docs/accounting_consolidation_migration_log.md`.
- Did not change code, tests, schema, or UI behavior.
