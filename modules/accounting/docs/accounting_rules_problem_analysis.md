# Accounting Rules Problem Analysis

## 1. Purpose

This document analyzes problems, risks, inconsistencies, and coverage gaps in the **currently implemented** accounting rules.

This document is:
- not an implementation task,
- not a patch,
- not a behavior change,
- not a correction plan,
- analysis only for later correction planning and task-card creation.

## 2. Source Documents

Primary source docs:
- `modules/accounting/docs/implemented_accounting_rules_reference.md`
- `modules/accounting/docs/implemented_accounting_rules_explained.md`

Implementation files inspected:
- `modules/accounting/service.py`
- `modules/accounting/current_rules/purchase_rules.py`
- `modules/accounting/current_rules/vendor_rules.py`
- `modules/accounting/current_rules/sales_rules.py`
- `modules/accounting/current_rules/customer_rules.py`
- `modules/accounting/current_rules/expense_rules.py`
- `modules/accounting/current_rules/bank_rules.py`
- `modules/accounting/current_rules/inventory_rules.py`
- `modules/accounting/validators.py`
- `database/schema.py`

Repository and consumer files inspected:
- `database/repositories/purchases_repo.py`
- `database/repositories/purchase_payments_repo.py`
- `database/repositories/vendor_advances_repo.py`
- `database/repositories/vendors_repo.py`
- `database/repositories/sales_repo.py`
- `database/repositories/sale_payments_repo.py`
- `database/repositories/customer_advances_repo.py`
- `database/repositories/customers_repo.py`
- `database/repositories/reporting_repo.py`
- `database/repositories/dashboard_repo.py`
- `database/repositories/sales_returns_helpers.py`
- `modules/purchase/controller.py`
- `modules/purchase/details.py`
- `modules/purchase/return_form.py`
- `modules/vendor/controller.py`
- `modules/sales/controller.py`
- `modules/sales/return_form.py`
- `modules/customer/controller.py`
- `modules/customer/history.py`
- `modules/customer/receipt_dialog.py`
- `widgets/invoice_preview.py`
- `resources/templates/invoices/*.html`
- `resources/templates/reports/*.html`

Accounting docs inspected:
- `modules/accounting/docs/purchase_vendor/vendor_purchase_migration_verification_audit.md`
- `modules/accounting/docs/purchase_vendor/vendor_purchase_accounting_consolidation_task_cards.md`
- `modules/accounting/docs/purchase_vendor/accounting_scenario_matrix_template.md`
- `modules/accounting/docs/customer_sales/accounting_consolidation_migration_log.md`
- `modules/accounting/docs/customer_sales/customer_sales_accounting_consolidation_task_cards.md`
- `modules/accounting/docs/expenses/accounting_consolidation_migration_log.md`
- `modules/accounting/docs/expenses/expenses_accounting_consolidation_task_cards.md`
- `modules/accounting/docs/expenses/vendor_purchase_overlap_risk.md`
- `AGENTS.md`

Tests inspected:
- `tests/accounting/test_vendor_purchase_*`
- `tests/accounting/test_customer_sales_*`
- `tests/accounting/test_expense_*`
- `tests/accounting/test_*_accounting_guardrails.py`
- `tests/accounting/test_*_accounting_contracts.py`

## 3. Analysis Method

- Every documented rule ID from both source docs was enumerated.
- Each rule was checked against actual code, schema/views/triggers, repository call sites, UI/report consumers, and existing tests.
- Findings were classified by severity and confidence.
- Judgement basis was recorded for each problem.
- No code, schema, tests, or UI behavior were changed.
- No test commands were run. This was static analysis only.

## 4. Severity and Confidence Definitions

Severity levels:

### Critical
Data can become financially incorrect, corrupt, unrecoverable, or misleading in a core flow.

### High
Important accounting result can be wrong in common scenarios, but data may still be recoverable.

### Medium
Problem affects edge cases, reports, consistency, maintainability, or user trust.

### Low
Minor inconsistency, weak naming, missing documentation, or low-risk missing test.

### Needs Investigation
Evidence suggests a possible issue, but not enough certainty to call it a bug.

Confidence levels:

### High
Direct evidence from code/tests/docs.

### Medium
Strong inference from implementation and tests.

### Low
Possible issue, but evidence is incomplete.

## 5. Rule Inventory Coverage

| Area | Rule IDs Found | Count | Present in Reference Doc | Present in Explained Doc | Notes |
|---|---|---:|---|---|---|
| Purchase | `PUR-RULE-001` to `PUR-RULE-006` | 6 | Yes | Yes | Full parity |
| Vendor | `VND-RULE-001` to `VND-RULE-006` | 6 | Yes | Yes | Full parity |
| Sales | `SAL-RULE-001` to `SAL-RULE-008` | 8 | Yes | Yes | Full parity |
| Customer | `CUST-RULE-001` to `CUST-RULE-006` | 6 | Yes | Yes | Full parity |
| Expense | `EXP-RULE-001` to `EXP-RULE-004` | 4 | Yes | Yes | Full parity |
| Bank/Cash | `BANK-RULE-001` to `BANK-RULE-003` | 3 | Yes | Yes | Full parity |
| Inventory | `INV-RULE-001` | 1 | Yes | Yes | Full parity |

Observed mismatches and notes:
- No rule-ID mismatch was found between the two source docs.
- No duplicate rule IDs were found.
- No standalone `STATUS-RULE-*` IDs exist in the current source docs.
- No standalone `REPORT-RULE-*` IDs exist in the current source docs.
- The required status/report sections below are synthesized from the documented rules and their actual consumers.
- The source docs reference `tests/accounting/test_vendor_purchase_payment_history.py`, but that file does not exist in `tests/accounting/`.
- The source docs reference `modules/purchase/invoice_preview.py`, but the active purchase invoice preview consumer is `widgets/invoice_preview.py`.
- The task prompt listed `modules/expenses/`; that directory does not exist. The active module is `modules/expense/`.

## 6. Executive Summary of Problems

| Problem ID | Severity | Area | Rule ID(s) | Short Problem | Confidence | Patch Later? |
|---|---|---|---|---|---|---|
| `ACC-PROB-001` | Medium | Purchase | `PUR-RULE-001` | Purchase outstanding is clamped in one API path and signed in another | High | Yes |
| `ACC-PROB-002` | Low | Purchase / Template | `PUR-RULE-002` | Purchase invoice preview context intentionally drops order discount | High | Yes |
| `ACC-PROB-003` | Medium | Purchase / Inventory | `PUR-RULE-005` | Returnable-quantity helper ignores current stock-on-hand | High | Yes |
| `ACC-PROB-004` | Low | Purchase / Docs | `PUR-RULE-006` | Rule docs cite a nonexistent payment-history test file | High | Yes |
| `ACC-PROB-005` | High | Vendor / Statement | `VND-RULE-003` | Vendor statement opening credit ignores carried return-credit balance | High | Yes |
| `ACC-PROB-006` | Medium | Vendor / Bank | `VND-RULE-002`, `BANK-RULE-001` | Auto-created vendor overpayment credit loses bank/payment metadata | High | Yes |
| `ACC-PROB-007` | High | Vendor / Refunds | `VND-RULE-006` | Supplier refund event does not verify refundable amount against returns/prior refunds | High | Yes |
| `ACC-PROB-008` | Medium | Sales / Migration | `SAL-RULE-004`, `INV-RULE-001` | Sale return processing is split between service and repo despite docs describing one consolidated rule | High | Yes |
| `ACC-PROB-009` | High | Sales / Bank | `SAL-RULE-004`, `BANK-RULE-002` | Sale return cash refunds are hard-coded as cash-only with no bank metadata path | High | Yes |
| `ACC-PROB-010` | Critical | Sales / Customer Credit | `SAL-RULE-005` | `SalePaymentsRepo` passes `customer_id=0` into overpayment conversion | High | Yes |
| `ACC-PROB-011` | High | Customer / Statement | `CUST-RULE-004` | Customer statement ignores requested date range and opening balance | High | Yes |
| `ACC-PROB-012` | High | Customer / Receivables | `CUST-RULE-006` | Customer receivable summary counts `posted` payments as if they reduce due | High | Yes |
| `ACC-PROB-013` | Medium | Customer / Validation | `CUST-RULE-001` | Customer credit event lacks method-detail validation parity with receipt validators | High | Yes |
| `ACC-PROB-014` | Medium | Expense / Accounting Risk | `EXP-RULE-001`, `EXP-RULE-003`, `EXP-RULE-004` | Expenses affect P&L and dashboard totals with no bank/cash linkage at all | High | Yes |
| `ACC-PROB-015` | High | Bank / Reporting | `BANK-RULE-001` | Bank ledger filters by transaction date, not cleared date | High | Yes |
| `ACC-PROB-016` | High | Bank / Customer Credit | `BANK-RULE-002`, `CUST-RULE-001`, `SAL-RULE-004` | Customer cash-movement view treats non-cash return credit as cash inflow | High | Yes |
| `ACC-PROB-017` | High | Dashboard / Reports | `SAL-RULE-008`, `PUR-RULE-001`, `REPORT` synthesis | Dashboard open payables use purchase header totals instead of net purchase totals after returns | High | Yes |
| `ACC-PROB-018` | Low | Sales / Invoice Context | `SAL-RULE-003` | Sale invoice financials facade is only partial; template consumers still assemble missing pieces elsewhere | High | Yes |
| `ACC-PROB-019` | Medium | Migration / Guardrails | `VND-RULE-003` | Guardrail tests miss a direct fallback import of accounting internals in `modules/vendor/controller.py` | High | Yes |
| `ACC-PROB-020` | Medium | Migration / Duplicate Logic | `SAL-RULE-004`, `INV-RULE-001` | Sale return math remains duplicated outside `AccountingService` in UI/helper code | High | Yes |

## 7. Purchase Rule Problems

### PUR-RULE-001: Purchase Financials Aggregation

#### Implemented behavior summary

The rule reads purchase totals from `purchase_detailed_totals`, uses cleared purchase payments plus applied vendor credit, reports prior refunds and return-credit totals, and exposes both a clamped outstanding view (`get_purchase_financials`) and a signed outstanding view (`get_purchase_outstanding`).

#### Files inspected

- `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_financials`, `get_purchase_outstanding`, `get_purchase_payment_status`, `recalculate_purchase_payment_status`
- `modules/accounting/service.py` — `get_purchase_financials`, `get_purchase_outstanding`, `get_purchase_remaining_due_header`
- `database/schema.py` — `purchase_detailed_totals`, purchase-payment triggers
- `database/repositories/purchases_repo.py` — `_with_purchase_totals`, `get_remaining_due_header`, `get_purchase_financials`
- `tests/accounting/test_vendor_purchase_outstanding.py`
- `tests/accounting/test_vendor_purchase_purchase_totals.py`
- `modules/accounting/docs/implemented_accounting_rules_reference.md`
- `modules/accounting/docs/implemented_accounting_rules_explained.md`

#### Problem analysis

##### ACC-PROB-001: Purchase outstanding is exposed with conflicting sign conventions

- Severity: Medium
- Confidence: High
- Judgement basis:
  - Direct contradiction with code/tests
  - Internal consistency concern
- Problem type:
  - Logical
  - Consistency
  - Reporting
- Evidence:
  - `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_financials`
  - `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_outstanding`
  - `modules/accounting/service.py` — `get_purchase_remaining_due_header`
  - `tests/accounting/test_vendor_purchase_outstanding.py` — `test_purchase_outstanding_matches_repo_remaining_due`
- Why this is a problem:
  - One API path clamps negative outstanding to zero, while another preserves negative outstanding for overpaid purchases.
  - Different screens/reports can therefore present different liability numbers for the same purchase.
- Current behavior:
  - `get_purchase_financials()` returns `outstanding = max(0, calc - cleared_direct - adv)`.
  - `get_purchase_outstanding()` returns signed `calc - paid - advance`.
  - `get_purchase_remaining_due_header()` wraps `get_purchase_outstanding(..., clamp=True)`.
- Expected or safer behavior:
  - A single documented convention should exist:
    - either always expose signed outstanding and let consumers clamp,
    - or always expose both signed and clamped values explicitly.
  - Based on current tests, this is an internal consistency concern, not a claim that one sign is definitely correct.
- Scenarios affected:
  - overpaid purchases,
  - purchases settled partly by manual header edits,
  - reports/screens mixing financial-summary vs header-remaining APIs.
- User/business impact:
  - Users can see zero due in one place and a negative due/credit situation in another.
- Data impact:
  - No immediate corruption, but presentation divergence can hide overpayment conditions.
- Tests currently covering it:
  - `tests/accounting/test_vendor_purchase_outstanding.py`
- Missing tests:
  - explicit UI/report parity test across all three APIs.
- Related rules:
  - `PUR-RULE-006`
  - `VND-RULE-005`
  - `STATUS` synthesis
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No direct test compares `get_purchase_financials().outstanding`, `get_purchase_outstanding()`, and `get_purchase_remaining_due_header()` in the same overpayment scenario.
- No test covers a purchase where header `paid_amount` is stale relative to ledger rows.

#### Edge cases not covered

- zero-total purchase,
- negative signed outstanding after refund plus credit note,
- rounding around `1e-9` status thresholds,
- direct SQL/header mutation bypassing ledger triggers.

#### Later correction priority

- Should fix

### PUR-RULE-002: Purchase Invoice Financials Context

#### Implemented behavior summary

The rule builds two contexts:
- `context`, which includes vendor, items, totals, payments, and a calculated remaining value,
- `preview_context`, which intentionally resets order discount to zero and total to subtotal.

#### Files inspected

- `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_invoice_financials`
- `modules/accounting/service.py` — `get_purchase_invoice_financials`
- `widgets/invoice_preview.py` — `_prepare_invoice_data`
- `resources/templates/invoices/purchase_invoice.html`
- `tests/accounting/test_vendor_purchase_invoice_financials.py`
- `modules/accounting/docs/purchase_vendor/vendor_purchase_migration_verification_audit.md`

#### Problem analysis

##### ACC-PROB-002: Purchase invoice preview context intentionally drops order discount

- Severity: Low
- Confidence: High
- Judgement basis:
  - Direct contradiction with code/docs
  - Reporting concern
- Problem type:
  - Reporting
  - Consistency
- Evidence:
  - `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_invoice_financials`
  - `widgets/invoice_preview.py` — uses `invoice.preview_context`
  - `resources/templates/invoices/purchase_invoice.html`
  - `modules/accounting/docs/purchase_vendor/vendor_purchase_migration_verification_audit.md` — "Invoice Preview Discount Fallback"
- Why this is a problem:
  - The preview consumer displays a subtotal-only total when an order discount exists.
  - The detail/invoice financial context and the preview context therefore disagree by design.
- Current behavior:
  - `preview_context["totals"]["order_discount"] = 0`
  - `preview_context["totals"]["total"] = subtotal`
- Expected or safer behavior:
  - If this is acceptable legacy behavior, it should be clearly documented as a reporting exception.
  - If not acceptable, preview and detail contexts should source the same totals.
- Scenarios affected:
  - discounted purchase invoices,
  - print previews,
  - audits comparing printed output with purchase details.
- User/business impact:
  - printed/ppreview invoice can overstate the payable amount.
- Data impact:
  - none; display-only divergence.
- Tests currently covering it:
  - invoice-context tests do not assert discount parity between `context` and `preview_context`.
- Missing tests:
  - template preview should reflect discounted totals when order discount exists, or else a test should lock the intended exception explicitly.
- Related rules:
  - `REPORT` synthesis
- Suggested later action:
  - verify with business rule

#### Missing or weak tests

- No test asserts purchase template totals against both `context` and `preview_context`.

#### Edge cases not covered

- order discount greater than subtotal,
- return plus order discount on printed invoice,
- multiple payments with preview refresh.

#### Later correction priority

- Could fix later

### PUR-RULE-003: Purchase Return Event Processing

#### Implemented behavior summary

The rule validates returnable quantity, validates stock-on-hand in base units, writes inventory return events, reads return snapshots, computes settlement amount, and then resolves settlement as supplier refund and/or vendor return credit.

#### Files inspected

- `modules/accounting/current_rules/purchase_rules.py` — `record_purchase_return_event`
- `modules/accounting/current_rules/inventory_rules.py` — `record_purchase_return_inventory_event`
- `modules/accounting/current_rules/vendor_rules.py` — `record_supplier_refund_event`, `record_vendor_advance_event`
- `database/schema.py` — `purchase_return_snapshots`, `purchase_return_valuations`, `v_stock_on_hand`
- `tests/accounting/test_vendor_purchase_return_event.py`
- `tests/accounting/test_vendor_purchase_return_valuation.py`
- `tests/accounting/test_vendor_purchase_supplier_refund.py`

#### Problem analysis

No clear problem found from current evidence.

Notes:
- The rule is heavily coupled to snapshot/trigger behavior in `database/schema.py`.
- The settlement formula is non-trivial and should stay under characterization tests before any correction work.

#### Missing or weak tests

- No direct test for zero or negative `qty_return` payload values.
- No direct test for mixed settlement metadata where part becomes cash refund and part becomes vendor credit.
- No direct test for multiple lines sharing the same `item_id` in one payload.

#### Edge cases not covered

- rounding on prorated order discount,
- repeated partial returns crossing from outstanding to refundable state,
- settlement metadata for non-cash credit-note mode,
- return after prior refund and prior return credit,
- missing or inactive vendor account in settlement metadata for return-credit mode.

#### Later correction priority

- Needs investigation

### PUR-RULE-004: Purchase Return Totals

#### Implemented behavior summary

The rule sums `purchase_return_valuations` rows for a purchase and returns total returned quantity and value.

#### Files inspected

- `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_return_values`, `get_purchase_return_totals`
- `database/schema.py` — `purchase_return_valuations`
- `tests/accounting/test_vendor_purchase_return_valuation.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No test for empty purchase with no returns.
- No test for ordering stability when transaction IDs are non-sequential by date.

#### Edge cases not covered

- multiple same-day return transactions,
- fractional quantities across UoMs,
- rounding in aggregate totals.

#### Later correction priority

- No action currently

### PUR-RULE-005: Purchase Returnable Quantities

#### Implemented behavior summary

The rule reports remaining returnable quantity per purchase item by subtracting already posted purchase-return inventory rows from original purchased quantity.

#### Files inspected

- `modules/accounting/current_rules/inventory_rules.py` — `get_purchase_returnable_quantities`
- `modules/accounting/current_rules/purchase_rules.py` — `record_purchase_return_event`
- `database/schema.py` — `v_stock_on_hand`
- `tests/accounting/test_vendor_purchase_return_valuation.py`
- `modules/purchase/return_form.py`

#### Problem analysis

##### ACC-PROB-003: Returnable quantity helper ignores current stock-on-hand

- Severity: Medium
- Confidence: High
- Judgement basis:
  - Direct contradiction with code/docs
  - Internal consistency concern
- Problem type:
  - Edge case
  - Consistency
  - Reporting
- Evidence:
  - `modules/accounting/current_rules/inventory_rules.py` — `get_purchase_returnable_quantities`
  - `modules/accounting/current_rules/purchase_rules.py` — `record_purchase_return_event` separately validates `v_stock_on_hand`
  - `modules/purchase/return_form.py` consumes financial/returnable info for UI
- Why this is a problem:
  - The helper reports what is contractually returnable against the original purchase, but not what is physically returnable from current stock.
  - The event writer later rejects returns that exceed current stock.
- Current behavior:
  - UI/helper can show a quantity as returnable.
  - write path can still reject it because stock-on-hand has since dropped.
- Expected or safer behavior:
  - Either expose both values:
    - contractual returnable quantity,
    - stock-available returnable quantity,
  - or clearly label the helper as not stock-aware.
- Scenarios affected:
  - items sold/adjusted after purchase,
  - backdated returns,
  - multi-step return preparation.
- User/business impact:
  - misleading return UI and failed submission after user fills a seemingly valid quantity.
- Data impact:
  - no corruption; write path still blocks.
- Tests currently covering it:
  - current tests cover prior-return subtraction, not stock depletion after purchase.
- Missing tests:
  - returnable quantity displayed > current stock but write path rejects.
- Related rules:
  - `PUR-RULE-003`
  - `INV-RULE-001`
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No characterization test combining returnable quantity with current stock depletion.

#### Edge cases not covered

- stock sold to zero after purchase,
- stock adjusted negative then rebuilt,
- mixed-UoM returnable quantities.

#### Later correction priority

- Should fix

### PUR-RULE-006: Purchase Payment History & Summary

#### Implemented behavior summary

The rule returns purchase payment rows, derives latest payment metadata, and reports paid amount, applied credit, remaining due, status, and overpayment converted to vendor credit.

#### Files inspected

- `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_payment_history`, `get_purchase_payment_summary`
- `database/repositories/purchase_payments_repo.py`
- `tests/accounting/test_vendor_purchase_payment_summary.py`
- `modules/accounting/docs/implemented_accounting_rules_reference.md`
- `modules/accounting/docs/implemented_accounting_rules_explained.md`

#### Problem analysis

##### ACC-PROB-004: Rule documentation cites a nonexistent purchase payment-history test

- Severity: Low
- Confidence: High
- Judgement basis:
  - Direct contradiction with docs/tests
- Problem type:
  - Test coverage
  - Maintainability
- Evidence:
  - `modules/accounting/docs/implemented_accounting_rules_reference.md`
  - `modules/accounting/docs/implemented_accounting_rules_explained.md`
  - `tests/accounting/` contains `test_vendor_purchase_payment_summary.py` but no `test_vendor_purchase_payment_history.py`
- Why this is a problem:
  - The docs overstate direct test coverage for payment-history behavior.
- Current behavior:
  - Summary tests assert some history ordering indirectly.
  - There is no separate dedicated payment-history test file.
- Expected or safer behavior:
  - Docs should point to the actual test file or a dedicated history test should exist later.
- Scenarios affected:
  - future maintenance,
  - audit/coverage review.
- User/business impact:
  - low; mainly affects developer confidence.
- Data impact:
  - none.
- Tests currently covering it:
  - `tests/accounting/test_vendor_purchase_payment_summary.py`
- Missing tests:
  - direct history-only characterization of ordering/metadata.
- Related rules:
  - `PUR-RULE-001`
- Suggested later action:
  - add tests

#### Missing or weak tests

- No direct test file for history-only behavior.
- No test for multiple uncleared purchase payments, although current vendor-payment validations largely reject them.

#### Edge cases not covered

- no payment rows,
- payment rows with missing bank labels,
- negative payment rows if inserted manually.

#### Later correction priority

- Could fix later

## 8. Vendor Rule Problems

### VND-RULE-001: Vendor Advance Credit

#### Implemented behavior summary

The rule writes positive vendor credit rows (`deposit` or `return_credit`) into `vendor_advances`, validates vendor/bank metadata through `validate_vendor_payment_metadata`, and exposes balance through `v_vendor_advance_balance`.

#### Files inspected

- `modules/accounting/current_rules/vendor_rules.py` — `record_vendor_advance_event`, `get_vendor_advance_balance`
- `modules/accounting/validators.py` — `validate_vendor_payment_metadata`
- `database/schema.py` — `vendor_advances`, vendor advance triggers, `v_vendor_advance_balance`
- `tests/accounting/test_vendor_purchase_vendor_advance_event.py`
- `tests/accounting/test_vendor_purchase_vendor_balance.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No direct test for `source_type='deposit'` with non-cash metadata details missing.
- No test for inactive vendor bank account in `record_vendor_advance_event`.

#### Edge cases not covered

- temporary vendor bank fields without permanent account,
- bank transfer with missing instrument number,
- same-day multiple advances and later auto-apply interactions.

#### Later correction priority

- No action currently

### VND-RULE-002: Vendor Payment Processing

#### Implemented behavior summary

The rule previews remaining due, caps the purchase-payment row at the due amount, converts any excess to vendor credit, writes the payment row, and writes an audit log.

#### Files inspected

- `modules/accounting/current_rules/vendor_rules.py` — `preview_vendor_payment_effect`, `_record_vendor_deposit_credit`, `record_vendor_payment_event`
- `database/schema.py` — `purchase_payments`, `vendor_advances`, `v_bank_ledger_ext`
- `database/repositories/purchase_payments_repo.py`
- `tests/accounting/test_vendor_purchase_vendor_payment_event.py`
- `tests/accounting/test_vendor_purchase_cash_movements.py`

#### Problem analysis

##### ACC-PROB-006: Auto-created vendor overpayment credit loses bank/payment metadata

- Severity: Medium
- Confidence: High
- Judgement basis:
  - Direct contradiction with code/tests
  - Data integrity concern
  - Reporting concern
- Problem type:
  - Data integrity
  - Bank/cash
  - Reporting
- Evidence:
  - `modules/accounting/current_rules/vendor_rules.py` — `_record_vendor_deposit_credit`
  - `database/schema.py` — `vendor_advances`
  - `modules/accounting/current_rules/bank_rules.py` — `get_bank_ledger`
  - `database/repositories/dashboard_repo.py` — `bank_movements_by_account`
- Why this is a problem:
  - Overpayment credit rows are inserted without method, account, instrument, or clearing metadata.
  - Those rows still contribute to vendor credit balances and can appear as bank outflows with null attribution.
- Current behavior:
  - the paid portion is captured in `purchase_payments`,
  - the overpaid portion is captured in `vendor_advances`,
  - only the purchase-payment row keeps bank metadata.
- Expected or safer behavior:
  - overpayment credit should preserve enough metadata to reconcile the full outgoing cash movement.
- Scenarios affected:
  - bank transfer or cheque overpayments,
  - account-based bank movement reporting,
  - audit of one payment split into due amount + excess credit.
- User/business impact:
  - cash left the company, but the credit portion may not tie back to the correct account in bank reports.
- Data impact:
  - reconciliation/reporting divergence, though the gross value is still captured.
- Tests currently covering it:
  - overpayment-credit creation is covered,
  - metadata propagation is not covered.
- Missing tests:
  - overpayment by bank method should preserve bank-account attribution across both resulting effects.
- Related rules:
  - `BANK-RULE-001`
  - `BANK-RULE-002`
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No test checks metadata on the auto-created credit row.
- No test checks `get_bank_ledger(account_id=...)` after a bank-method overpayment.

#### Edge cases not covered

- overpayment equal to full payment amount,
- payment amount that rounds just above due,
- non-cash payment methods with temp vendor bank details.

#### Later correction priority

- Should fix

### VND-RULE-003: Vendor Statement Generation

#### Implemented behavior summary

The rule builds a chronological vendor statement using purchases, cleared purchase payments, cleared supplier refunds, and vendor-advance ledger rows. It computes opening payable and opening credit separately when a start date is provided.

#### Files inspected

- `modules/accounting/current_rules/vendor_rules.py` — `get_vendor_statement`
- `database/schema.py` — `purchase_detailed_totals`, `purchase_refunds`, `vendor_advances`, `v_vendor_advance_balance`
- `database/repositories/reporting_repo.py` — vendor aging / vendor headers
- `modules/vendor/controller.py` — `build_vendor_statement`
- `tests/accounting/test_vendor_purchase_vendor_statement.py`

#### Problem analysis

##### ACC-PROB-005: Vendor statement opening credit ignores carried return-credit balance

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with code
  - Internal consistency concern
- Problem type:
  - Accounting correctness
  - Consistency
  - Reporting
- Evidence:
  - `modules/accounting/current_rules/vendor_rules.py` — `get_vendor_statement`
  - `database/schema.py` — `v_vendor_advance_balance`
- Why this is a problem:
  - `opening_credit` sums only pre-period `vendor_advances.source_type='deposit'`.
  - Positive pre-period `return_credit` rows are excluded even though they contribute to actual vendor credit balance.
- Current behavior:
  - deposit credit carries into statement opening credit,
  - unapplied return credit does not.
- Expected or safer behavior:
  - opening credit should reconcile with the same credit basis used by vendor balance unless business rules intentionally split deposit credit vs return credit.
  - No such split rule was found in docs or tests.
- Scenarios affected:
  - vendor statements starting after prior purchase returns,
  - vendors carrying forward unapplied return credits.
- User/business impact:
  - statement can understate vendor credit carried into the period.
- Data impact:
  - reporting divergence only; underlying rows remain intact.
- Tests currently covering it:
  - existing statement tests cover deposit/opening-payable behavior, not carried return credit.
- Missing tests:
  - start-date statement with pre-period unapplied `return_credit`.
- Related rules:
  - `VND-RULE-001`
  - `PUR-RULE-003`
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No test for opening statement balances with return-credit carry-forward.
- No test for `show_return_origins=True` path.

#### Edge cases not covered

- statement period beginning after both deposit credit and return credit,
- mixed cleared and uncleared historical rows,
- same-day purchase/payment/refund ordering.

#### Later correction priority

- Must fix before release

### VND-RULE-004: Vendor Credit Allocation (FIFO Auto-Apply)

#### Implemented behavior summary

The rule previews FIFO credit allocation across open purchases, writes one positive vendor credit row, then writes negative `applied_to_purchase` rows in FIFO order inside a transaction.

#### Files inspected

- `modules/accounting/current_rules/vendor_rules.py` — `preview_vendor_advance_allocation`, `record_vendor_advance_with_auto_apply`
- `database/schema.py` — vendor-advance no-overdraw and remaining-due triggers
- `tests/accounting/test_vendor_purchase_advance_allocation.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No test for date ties across purchases.
- No test for auto-apply using a `return_credit` source rather than `deposit`.

#### Edge cases not covered

- transaction already open before `BEGIN IMMEDIATE`,
- tiny rounding residue left as remaining credit,
- vendor with no open purchases.

#### Later correction priority

- No action currently

### VND-RULE-005: Vendor Open Purchases

#### Implemented behavior summary

The rule returns purchases with positive outstanding amount based on net purchase total minus paid amount minus applied credit.

#### Files inspected

- `modules/accounting/current_rules/vendor_rules.py` — `get_vendor_open_purchases`
- `database/schema.py` — `purchase_detailed_totals`
- `tests/accounting/test_vendor_purchase_open_purchases.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No test for overpaid purchase exclusion with negative balance.
- No test for vendor with mixed stale header totals and recalculated view totals.

#### Edge cases not covered

- rounding around `1e-9`,
- backdated returns after the purchase is fully paid.

#### Later correction priority

- No action currently

### VND-RULE-006: Supplier Refunds

#### Implemented behavior summary

The rule validates supplier-refund metadata and inserts a cleared row into `purchase_refunds`, then writes an audit log. It can also be triggered indirectly from purchase-return settlement.

#### Files inspected

- `modules/accounting/current_rules/vendor_rules.py` — `record_supplier_refund_event`, `get_supplier_refunds_for_purchase`
- `modules/accounting/current_rules/purchase_rules.py` — `record_purchase_return_event`
- `database/schema.py` — `purchase_refunds`
- `tests/accounting/test_vendor_purchase_supplier_refund.py`

#### Problem analysis

##### ACC-PROB-007: Supplier refund event does not verify refundable amount against returns or prior refunds

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with documented behavior
  - Accounting principle concern
- Problem type:
  - Accounting correctness
  - Business rule
  - Data integrity
- Evidence:
  - `modules/accounting/current_rules/vendor_rules.py` — `record_supplier_refund_event`
  - `modules/accounting/docs/implemented_accounting_rules_reference.md` describes supplier refunds as matching against returned values
  - `tests/accounting/test_vendor_purchase_supplier_refund.py` covers insert shape only, not refund cap validation
- Why this is a problem:
  - The write path accepts any positive refund amount and does not reconcile it with purchase return value, prior refunds, or prior return credits.
- Current behavior:
  - direct call inserts a refund row if metadata is valid.
- Expected or safer behavior:
  - refund amount should be capped or at least validated against unsettled return value for that purchase.
- Scenarios affected:
  - manual supplier refund entry without a preceding return,
  - repeated refunds against the same return,
  - refund greater than the remaining refundable amount.
- User/business impact:
  - purchase can show more vendor cash returned than the return event justified.
- Data impact:
  - financially misleading purchase settlement history.
- Tests currently covering it:
  - insert shape and indirect purchase-return behavior only.
- Missing tests:
  - refund without return,
  - refund above unresolved return value,
  - repeated refunds exceeding purchase-return settlement.
- Related rules:
  - `PUR-RULE-003`
  - `BANK-RULE-001`
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No negative test for over-refund.
- No test for direct service call before any purchase return.

#### Edge cases not covered

- partial refunds across multiple return events,
- refund after return-credit note already issued,
- refund after purchase already over-refunded.

#### Later correction priority

- Must fix before release

## 9. Sales Rule Problems

### SAL-RULE-001: Sale Financial Summary

#### Implemented behavior summary

The rule reads `sale_detailed_totals` and `sale_receivable_totals` to report gross total, returned value, net total, paid amount, applied credit, and outstanding amount.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `get_sale_financial_summary`
- `database/schema.py` — `sale_detailed_totals`, `sale_receivable_totals`
- `database/repositories/sales_repo.py` — sale detail summary helpers
- `tests/accounting/test_customer_sales_sale_outstanding.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No direct test for overpaid sale where header paid amount is clamped but refund history exists.

#### Edge cases not covered

- zero-total sale,
- rounding at `1e-9`,
- sale with return credit but no direct receipt.

#### Later correction priority

- No action currently

### SAL-RULE-002: Sale Totals Calculation

#### Implemented behavior summary

The rule reads subtotal, order discount, returned value, and net total from `sale_detailed_totals` and also provides preview math for item-level and order-level discounts.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `get_sale_totals`, `preview_sale_total`
- `database/schema.py` — `sale_detailed_totals`
- `tests/accounting/test_customer_sales_sale_totals.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No test for order discount larger than subtotal.

#### Edge cases not covered

- negative order discount stored directly in DB,
- rounding across many item discounts.

#### Later correction priority

- No action currently

### SAL-RULE-003: Sale Invoice Financials Context

#### Implemented behavior summary

The rule returns only settlement-related invoice context: returns, return credit, applied credit, paid amount, remaining amount, returned value, and net total. Controllers/templates assemble additional document/item/customer fields elsewhere.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `get_sale_invoice_financials`
- `modules/sales/controller.py` — invoice enrichment path
- `resources/templates/invoices/sale_invoice.html`
- `tests/accounting/test_customer_sales_invoice_financials.py`

#### Problem analysis

##### ACC-PROB-018: Sale invoice financials facade is only partial; consumers still assemble missing values elsewhere

- Severity: Low
- Confidence: High
- Judgement basis:
  - Direct contradiction with documentation
  - Reporting concern
- Problem type:
  - Reporting
  - Migration
  - Maintainability
- Evidence:
  - `modules/accounting/current_rules/sales_rules.py` — `get_sale_invoice_financials`
  - `modules/sales/controller.py` — still fetches totals, company context, and payments separately
  - `resources/templates/invoices/sale_invoice.html` expects richer context than the service returns by itself
- Why this is a problem:
  - The docs describe a fuller invoice-financials rule than the service actually provides.
  - Template/report consumers are not fully sourced from one accounting API.
- Current behavior:
  - accounting facade returns partial settlement context only.
- Expected or safer behavior:
  - Either document the facade as partial, or consolidate invoice-financial data into one source.
- Scenarios affected:
  - future template consumers calling the facade directly,
  - migration/completeness audits.
- User/business impact:
  - mostly developer-facing until a new consumer assumes the facade is complete.
- Data impact:
  - none directly.
- Tests currently covering it:
  - current tests only assert the partial fields.
- Missing tests:
  - end-to-end invoice context parity test for service + controller + template.
- Related rules:
  - `REPORT` synthesis
- Suggested later action:
  - analyze further

#### Missing or weak tests

- No test that the service alone provides everything required by the sale invoice template.

#### Edge cases not covered

- return credit plus applied credit plus refunds together on one invoice,
- missing payment rows with nonzero header paid amount.

#### Later correction priority

- Could fix later

### SAL-RULE-004: Sale Return Event Processing

#### Implemented behavior summary

The service settlement rule computes settlement due from return value and remaining due, inserts a negative `sale_payments` row for immediate cash refund, inserts `customer_advances` return credit for any remainder, and returns a settlement effect DTO.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `record_sale_return_event`
- `database/repositories/sales_repo.py` — sale return orchestration
- `modules/sales/return_form.py`
- `database/repositories/sales_returns_helpers.py`
- `database/schema.py` — `sale_return_snapshots`, `sale_payments`, customer-advance triggers
- `tests/accounting/test_customer_sales_sale_return_financials.py`

#### Problem analysis

##### ACC-PROB-008: Sale return processing is only partially consolidated

- Severity: Medium
- Confidence: High
- Judgement basis:
  - Migration/consolidation concern
  - Direct contradiction with docs
- Problem type:
  - Migration
  - Maintainability
  - Consistency
- Evidence:
  - `modules/accounting/current_rules/sales_rules.py` — `record_sale_return_event` handles settlement only
  - `database/repositories/sales_repo.py` — still writes inventory return rows and validates return quantities before calling the service
- Why this is a problem:
  - The documented rule reads as one consolidated accounting rule, but the actual behavior is split across service, repository, triggers, and UI helpers.
- Current behavior:
  - inventory posting and snapshot capture happen outside the accounting service,
  - settlement happens inside the service.
- Expected or safer behavior:
  - consolidation docs should reflect the split, or the implementation should later be fully centralized.
- Scenarios affected:
  - future refactors assuming the service alone performs the full sale return.
- User/business impact:
  - high maintenance risk; moderate direct user risk.
- Data impact:
  - split logic increases chance of future partial updates.
- Tests currently covering it:
  - current tests validate settlement pieces, not full service ownership.
- Missing tests:
  - contract test asserting where full sale-return responsibilities currently live.
- Related rules:
  - `INV-RULE-001`
  - `ACC-PROB-020`
- Suggested later action:
  - create correction task card

##### ACC-PROB-009: Immediate sale refunds are hard-coded as cash-only and cannot carry bank metadata

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with code
  - Bank/cash consistency concern
- Problem type:
  - Accounting correctness
  - Business rule
  - Bank/cash
- Evidence:
  - `modules/accounting/current_rules/sales_rules.py` — `record_sale_return_event`
  - inserted row uses fixed `method='Cash'`, `instrument_type='other'`, no bank account fields
- Why this is a problem:
  - A sale return can create an actual cash/bank outflow, but this rule has no way to represent refund-by-bank or refund-by-cheque.
- Current behavior:
  - any immediate refund becomes a negative `sale_payments` cash row.
- Expected or safer behavior:
  - settlement payload should carry refund payment metadata if non-cash refunds are allowed.
  - If only cash refunds are allowed, that business rule should be explicit in docs/UI/tests.
- Scenarios affected:
  - return refunded back to bank/cheque,
  - bank-reconciliation reports,
  - refund method auditing.
- User/business impact:
  - refund method records can be materially wrong.
- Data impact:
  - bank ledger can miss or misclassify the real outgoing account.
- Tests currently covering it:
  - no test asserts alternative refund methods because the API does not expose them.
- Missing tests:
  - explicit policy test for allowed refund methods.
- Related rules:
  - `BANK-RULE-001`
  - `BANK-RULE-002`
- Suggested later action:
  - verify with business rule

#### Missing or weak tests

- No test for bank-based refund method because the API cannot express it.
- No test for full return-processing ownership boundary between repo and service.

#### Edge cases not covered

- multiple returns with mixed refund and credit,
- refund after prior bounced receipt,
- return after customer credit application.

#### Later correction priority

- Must fix before release

### SAL-RULE-005: Customer Payment Recording & Overpayment Conversion

#### Implemented behavior summary

The service writes a `sale_payments` row and, if the row is cleared, converts any excess above receivable into a positive `customer_advances` deposit row.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `record_customer_payment_event`, `_handle_overpayment`
- `database/repositories/sale_payments_repo.py` — `record_payment_with_conn`
- `database/schema.py` — `sale_payments`, `customer_advances`, overpayment columns
- `tests/accounting/test_customer_sales_payment_event.py`

#### Problem analysis

##### ACC-PROB-010: `SalePaymentsRepo` passes `customer_id=0` into overpayment conversion

- Severity: Critical
- Confidence: High
- Judgement basis:
  - Direct contradiction with code
  - Data integrity concern
- Problem type:
  - Data integrity
  - Accounting correctness
  - Migration
- Evidence:
  - `database/repositories/sale_payments_repo.py` — `record_payment_with_conn` builds `CustomerPaymentPayload(customer_id=0, ...)`
  - `modules/accounting/current_rules/sales_rules.py` — `_handle_overpayment` inserts `customer_advances` using `payload.customer_id`
- Why this is a problem:
  - When a repo-recorded payment clears at insert time and is an overpayment, the service tries to create customer credit for customer `0`.
- Current behavior:
  - direct service tests pass because they provide the real customer ID,
  - repo path hard-codes `0`.
- Expected or safer behavior:
  - repo must pass the sale's actual customer ID, or the service must derive it from `sale_id`.
- Scenarios affected:
  - cleared overpayments recorded through `SalePaymentsRepo`.
- User/business impact:
  - overpayment conversion can fail or mis-post credit.
- Data impact:
  - possible transaction failure or wrong customer-credit row.
- Tests currently covering it:
  - direct service payment tests.
- Missing tests:
  - repo-level cleared overpayment conversion test.
- Related rules:
  - `SAL-RULE-006`
  - `CUST-RULE-001`
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No repo-path overpayment test.
- No test for bank-method overpayment conversion at insert time.

#### Edge cases not covered

- exact due amount,
- multiple cleared payments causing later excess,
- posted payment later cleared after repo insert path.

#### Later correction priority

- Must fix before release

### SAL-RULE-006: Customer Payment Status Transition & Reversal

#### Implemented behavior summary

The rule updates clearing state for sale payments, performs overpayment reconciliation when moving to cleared, and reopens cleared/bounced payments by moving them back to pending and reversing any converted overpayment credit if possible.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `get_sale_payment_status`, `recalculate_sale_payment_status`, `update_customer_payment_state`, `_reconcile_overpayment_on_clear`, `reopen_customer_payment_state`
- `database/repositories/sale_payments_repo.py`
- `database/schema.py` — sale-payment state triggers and reversal table
- `tests/accounting/test_customer_sales_payment_status.py`

#### Problem analysis

No clear problem found from current evidence.

Notes:
- The state machine is complex and partly enforced in both Python and triggers.
- This area remains high-risk for future change even though no direct correctness contradiction was proven here.

#### Missing or weak tests

- No test for reopen after bounced state when no overpayment existed.
- No test for clearing state transitions combined with multiple payment rows and prior refunds.

#### Edge cases not covered

- partial overpayment already partly consumed,
- repeated clear/reopen cycles,
- date semantics of `CURRENT_DATE` reversal credit row.

#### Later correction priority

- Needs investigation

### SAL-RULE-007: Quotation Conversion

#### Implemented behavior summary

The rule validates quotation status and marks the quotation as accepted when converting.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `validate_quotation_conversion`, `record_quotation_conversion_event`
- `database/schema.py` — quotation payment-blocking triggers
- `tests/accounting/test_customer_sales_quotation_behavior.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No test for duplicate conversion race.

#### Edge cases not covered

- quotation with missing customer,
- quotation already linked to a sale via `source_type/source_id`.

#### Later correction priority

- No action currently

### SAL-RULE-008: Sale COGS Aggregation

#### Implemented behavior summary

The rule reads sale COGS from `sale_item_cogs` and the sales dashboard/profit summary uses `sale_financial_events`.

#### Files inspected

- `modules/accounting/current_rules/sales_rules.py` — `get_sale_cogs`, `get_sales_profit_summary`, `get_sales_dashboard_metrics`
- `database/schema.py` — `sale_item_cogs`, `sale_financial_events`
- `database/repositories/dashboard_repo.py`
- `tests/accounting/test_customer_sales_reports.py`

#### Problem analysis

##### ACC-PROB-017: Dashboard open payables use purchase header totals instead of net purchase totals after returns

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with code
  - Reporting concern
- Problem type:
  - Reporting
  - Consistency
- Evidence:
  - `modules/accounting/current_rules/sales_rules.py` — `get_sales_dashboard_metrics` CTE `all_payables`
  - `database/repositories/dashboard_repo.py` — `summary_metrics` and `open_payables`
  - `modules/accounting/current_rules/purchase_rules.py` — purchase outstanding uses `purchase_detailed_totals`
- Why this is a problem:
  - dashboard payables are derived from `p.total_amount - paid_amount - advance_payment_applied`.
  - purchase outstanding elsewhere is based on `purchase_detailed_totals.calculated_total_amount`, which is net of returns.
- Current behavior:
  - a purchase with returns can show lower outstanding in purchase screens and higher open payables in dashboard metrics.
- Expected or safer behavior:
  - dashboard/report payables should align with the same canonical purchase total used by accounting service.
- Scenarios affected:
  - purchase returns,
  - header total mismatch vs calculated total,
  - AP dashboard review.
- User/business impact:
  - dashboard payable totals can be overstated.
- Data impact:
  - reporting divergence only.
- Tests currently covering it:
  - current dashboard tests do not include purchase returns affecting open payables.
- Missing tests:
  - dashboard open payables with returned-value reductions.
- Related rules:
  - `PUR-RULE-001`
  - `REPORT` synthesis
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No direct `get_sale_cogs` unit test.
- No dashboard test with purchase returns affecting open payables.

#### Edge cases not covered

- sale return reversing COGS after purchase-layer changes,
- empty event set,
- date-boundary event inclusion.

#### Later correction priority

- Should fix

## 10. Customer Rule Problems

### CUST-RULE-001: Customer Advances & Credit Event

#### Implemented behavior summary

The rule records positive customer credit rows (`deposit` or `return_credit`) with optional method and company bank account metadata.

#### Files inspected

- `modules/accounting/current_rules/customer_rules.py` — `record_customer_credit_event`, `list_customer_credit_ledger`
- `database/repositories/customer_advances_repo.py`
- `modules/accounting/validators.py` — `validate_customer_payment_metadata`
- `tests/accounting/test_customer_sales_customer_credit_event.py`

#### Problem analysis

##### ACC-PROB-013: Customer credit event lacks method-detail validation parity with receipt validators

- Severity: Medium
- Confidence: High
- Judgement basis:
  - Direct contradiction with code
  - Business rule concern
- Problem type:
  - Business rule
  - Consistency
  - Data integrity
- Evidence:
  - `modules/accounting/current_rules/customer_rules.py` — `record_customer_credit_event`
  - `modules/accounting/validators.py` — `validate_customer_payment_metadata`
  - `database/repositories/customer_advances_repo.py` applies stronger validation in repo wrapper
- Why this is a problem:
  - The public accounting service allows non-cash customer credit rows without the same bank/reference validation used for customer payments and repo wrappers.
- Current behavior:
  - service checks method membership and active bank account only.
  - repo wrapper adds additional method/reference rules.
- Expected or safer behavior:
  - service-level validation should be authoritative for public accounting writes.
- Scenarios affected:
  - direct service usage,
  - future controller/repo rewiring that bypasses wrapper-specific checks.
- User/business impact:
  - inconsistent acceptance rules for similar financial metadata.
- Data impact:
  - incomplete audit trail on customer credit entries.
- Tests currently covering it:
  - current tests cover deposit and return-credit happy paths.
- Missing tests:
  - non-cash credit event without bank/reference details should be tested and policy-defined.
- Related rules:
  - `SAL-RULE-005`
  - `BANK-RULE-003`
- Suggested later action:
  - verify with business rule

#### Missing or weak tests

- No negative test for bank transfer credit without reference.
- No negative test for cheque/card credit without bank account.

#### Edge cases not covered

- invalid non-cash metadata,
- return-credit row without source sale,
- inactive customer handling.

#### Later correction priority

- Should fix

### CUST-RULE-002: Customer Credit Application

#### Implemented behavior summary

The rule validates target sale and amount, then inserts a negative `customer_advances` row with `source_type='applied_to_sale'`.

#### Files inspected

- `modules/accounting/current_rules/customer_rules.py` — `record_customer_credit_application_event`
- `database/schema.py` — customer-advance no-overdraw and not-exceed-remaining-due triggers
- `tests/accounting/test_customer_sales_credit_application.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No test for same customer applying credit to multiple sales on the same date.

#### Edge cases not covered

- rounding on remaining due,
- race between two simultaneous credit applications.

#### Later correction priority

- No action currently

### CUST-RULE-003: Customer History Timeline

#### Implemented behavior summary

The rule assembles customer sales, sale returns, payment rows, credit rows, and an event timeline ordered by date and event kind.

#### Files inspected

- `modules/accounting/current_rules/customer_rules.py` — `get_customer_history`, `_timeline`
- `modules/customer/history.py`
- `tests/accounting/test_customer_sales_customer_statement.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No test for a timeline containing sale return, refund, deposit, and credit application together.

#### Edge cases not covered

- same-day event ordering across all event types,
- negative balance transitions after refund reversal.

#### Later correction priority

- No action currently

### CUST-RULE-004: Customer Statement

#### Implemented behavior summary

The rule turns the customer-advance ledger into a statement with debit/credit rows and a running balance.

#### Files inspected

- `modules/accounting/current_rules/customer_rules.py` — `get_customer_statement`
- `database/schema.py` — `v_customer_advance_balance`
- `tests/accounting/test_customer_sales_customer_statement.py`

#### Problem analysis

##### ACC-PROB-011: Customer statement ignores requested date range and opening balance

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with code/API
  - Reporting concern
- Problem type:
  - Reporting
  - Logical
  - Test coverage
- Evidence:
  - `modules/accounting/current_rules/customer_rules.py` — `get_customer_statement`
- Why this is a problem:
  - The API accepts `start_date` and `end_date`, but the query reads all customer-advance rows and always reports `opening_balance=0`.
- Current behavior:
  - filtered dates are echoed back in the DTO only.
  - they do not affect entries or opening balance.
- Expected or safer behavior:
  - statement entries should be filtered to the period,
  - opening balance should reflect pre-period running balance.
- Scenarios affected:
  - any date-bounded customer statement.
- User/business impact:
  - statements can be materially misleading for audits and period reports.
- Data impact:
  - none; read-model bug.
- Tests currently covering it:
  - current tests cover timeline/history shape, not date-bounded statement semantics.
- Missing tests:
  - date-filtered statement with pre-period opening balance.
- Related rules:
  - `REPORT` synthesis
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No test for `start_date/end_date`.
- No test for opening balance != 0.

#### Edge cases not covered

- empty period with nonzero opening balance,
- statement period containing only negative application rows.

#### Later correction priority

- Must fix before release

### CUST-RULE-005: Customer Aging Report

#### Implemented behavior summary

The rule delegates aging to `ReportingRepo.customer_headers_as_of_batch`.

#### Files inspected

- `modules/accounting/current_rules/customer_rules.py` — `get_customer_aging`
- `database/repositories/reporting_repo.py` — customer aging helpers
- `tests/accounting/test_customer_sales_reports.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No accounting test directly asserting aging with returns and credits together.

#### Edge cases not covered

- cutoff before first sale,
- aging after bounced payment reopen.

#### Later correction priority

- No action currently

### CUST-RULE-006: Customer Receivable Summary

#### Implemented behavior summary

The rule returns credit balance, sales count, open due sum, and last activity dates using direct SQL.

#### Files inspected

- `modules/accounting/current_rules/customer_rules.py` — `get_customer_receivable_summary`
- `database/schema.py` — `sale_receivable_totals`
- `database/repositories/customers_repo.py`
- `tests/accounting/test_customer_sales_reports.py`

#### Problem analysis

##### ACC-PROB-012: Customer receivable summary counts `posted` payments as if they reduce due

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with internal accounting invariant
  - Consistency concern
- Problem type:
  - Accounting correctness
  - Consistency
  - Reporting
- Evidence:
  - `modules/accounting/current_rules/customer_rules.py` — `get_customer_receivable_summary`
  - query subtracts `sale_payments` where `clearing_state IN ('posted','cleared')`
  - canonical receivable logic elsewhere uses `sale_receivable_totals` / cleared rollups
- Why this is a problem:
  - Summary can understate receivables by treating uncleared posted payments as if cash were already applied.
- Current behavior:
  - `open_due_sum` is not sourced from `sale_receivable_totals.remaining_due`.
- Expected or safer behavior:
  - receivable summary should align with canonical receivable totals or explicitly define a separate "including posted" metric.
- Scenarios affected:
  - posted-but-not-cleared customer receipts,
  - bank methods with settlement lag.
- User/business impact:
  - customer balances and open receivable summaries can be understated.
- Data impact:
  - read-model divergence only.
- Tests currently covering it:
  - no direct test for posted vs cleared behavior.
- Missing tests:
  - summary with one posted payment and no cleared payment.
- Related rules:
  - `SAL-RULE-006`
  - `REPORT` synthesis
- Suggested later action:
  - create correction task card

#### Missing or weak tests

- No direct summary test for posted receipts.

#### Edge cases not covered

- posted negative refund,
- mixture of posted and cleared receipts on same sale.

#### Later correction priority

- Must fix before release

## 11. Expense / Expanse Rule Problems

### EXP-RULE-001: Expense Lifecycle write events

#### Implemented behavior summary

The rule validates description/amount/date and writes create/update/delete operations directly to `expenses`.

#### Files inspected

- `modules/accounting/current_rules/expense_rules.py` — `record_expense_create_event`, `record_expense_update_event`, `record_expense_delete_event`
- `modules/accounting/validators.py` — `validate_expense_input`
- `database/schema.py` — `expenses`
- `tests/accounting/test_expense_write_events.py`

#### Problem analysis

##### ACC-PROB-014: Expenses affect financial totals with no bank/cash linkage at all

- Severity: Medium
- Confidence: High
- Judgement basis:
  - Accounting principle concern
  - Architectural/accounting-risk issue
- Problem type:
  - Accounting correctness
  - Architectural risk
  - Reporting
- Evidence:
  - `database/schema.py` — `expenses` has only description/amount/date/category
  - `modules/accounting/current_rules/expense_rules.py` writes expense rows only
  - `modules/accounting/docs/expenses/vendor_purchase_overlap_risk.md`
- Why this is a problem:
  - Expenses reduce profit/loss and dashboard totals, but there is no payment-status, cash/bank, vendor, or payable linkage.
- Current behavior:
  - expense writes immediately affect expense totals and P&L.
- Expected or safer behavior:
  - This is not necessarily a bug in a simple app, but it is an architectural accounting risk that should be explicitly accepted or corrected later.
- Scenarios affected:
  - deferred-payment expenses,
  - reimbursable expenses,
  - bank reconciliation,
  - duplicate recording alongside purchase/vendor flows.
- User/business impact:
  - profit figures can move without any matching cash trail.
- Data impact:
  - no row corruption; weak accounting traceability.
- Tests currently covering it:
  - CRUD tests only.
- Missing tests:
  - explicit documentation/acceptance tests for no-bank-link expense model.
- Related rules:
  - `EXP-RULE-003`
  - `EXP-RULE-004`
  - `BANK` synthesis
- Suggested later action:
  - verify with business rule

#### Missing or weak tests

- No test for expense model limitations around cash/bank traceability.

#### Edge cases not covered

- negative amount at DB-level bypass,
- category foreign-key invalid when foreign keys are disabled,
- expense dated outside reporting range but later edited.

#### Later correction priority

- Should fix

### EXP-RULE-002: Expense Category write events

#### Implemented behavior summary

The rule validates category names and writes create/update/delete operations for expense categories.

#### Files inspected

- `modules/accounting/current_rules/expense_rules.py` — category CRUD methods
- `modules/accounting/validators.py` — `validate_expense_category_input`
- `tests/accounting/test_expense_category_lifecycle.py`

#### Problem analysis

No clear problem found from current evidence.

#### Missing or weak tests

- No concurrency/race test for duplicate category names.

#### Edge cases not covered

- whitespace-only rename to same name,
- case-insensitive duplicate semantics.

#### Later correction priority

- No action currently

### EXP-RULE-003: Expense Dashboard & Profit-Loss summaries

#### Implemented behavior summary

The rule returns dashboard expense totals and P&L expense breakdown totals from expense rows only.

#### Files inspected

- `modules/accounting/current_rules/expense_rules.py` — `get_dashboard_expense_total`, `get_profit_loss_expense_summary`
- `database/repositories/dashboard_repo.py`
- `database/repositories/reporting_repo.py`
- `tests/accounting/test_expense_dashboard_totals.py`
- `tests/accounting/test_expense_profit_loss_summary.py`

#### Problem analysis

`ACC-PROB-014` also applies here.

No additional rule-specific problem was proven beyond the architecture/tracing risk already listed.

#### Missing or weak tests

- No test for expense totals reconciling against any bank/cash source because none exists.

#### Edge cases not covered

- empty category set,
- negative correction rows if inserted manually.

#### Later correction priority

- Needs investigation

### EXP-RULE-004: Expense Reporting & Row reads

#### Implemented behavior summary

The rule returns expense rows, screen totals, report totals, and report lines from the `expenses` table with different grouping rules for screen vs report consumers.

#### Files inspected

- `modules/accounting/current_rules/expense_rules.py` — `list_expense_rows`, `get_expense_screen_category_totals`, `get_expense_report_category_totals`, `get_expense_report_lines`
- `database/repositories/expenses_repo.py`
- `database/repositories/reporting_repo.py`
- `tests/accounting/test_expense_row_reads.py`
- `tests/accounting/test_expense_screen_totals.py`
- `tests/accounting/test_expense_report_reads.py`

#### Problem analysis

`ACC-PROB-014` also applies here.

No additional rule-specific problem was proven from current evidence.

#### Missing or weak tests

- No explicit parity test showing why screen totals include zero-amount named categories while report totals exclude them.

#### Edge cases not covered

- category renamed between row read and total read,
- very large result sets / pagination behavior.

#### Later correction priority

- Needs investigation

## 12. Bank / Cash Rule Problems

| Rule ID | Trigger | Problem ID(s) | Current Behavior | Problem | Severity | Confidence | Suggested Later Action |
|---|---|---|---|---|---|---|---|
| `BANK-RULE-001` | Bank-ledger reads | `ACC-PROB-006`, `ACC-PROB-015` | Aggregates `v_bank_ledger_ext` plus vendor advances | Date semantics differ from cleared-date reads; auto-credit metadata can be missing | High | High | Create correction task cards |
| `BANK-RULE-002` | Vendor/customer cash movement reads | `ACC-PROB-009`, `ACC-PROB-016` | Vendor side uses cleared payments/refunds and deposit advances; customer side also includes return credits as cash movements | Customer side treats non-cash return credit as inflow; sale-refund method path is cash-only | High | High | Create correction task cards |
| `BANK-RULE-003` | Payment metadata validation | `ACC-PROB-013` | Validation is stronger for some paths than others | Public service writes do not consistently use the strongest validator path | Medium | High | Verify and consolidate later |

Detailed notes:

- Duplicate bank movement risk:
  - No direct duplicate was proven for vendor overpayment because purchase payment and excess credit split the same real cash amount into two rows.
  - The problem is metadata attribution, not proven double counting.
- Missing reversal risk:
  - Sale-return refunds create negative `sale_payments` rows, but there is no rich refund-metadata reversal model.
- Payment method inconsistencies:
  - Vendor outgoing methods do not allow `Card` in validators.
  - Customer credit event does allow `Card`.
  - Sale return refunds do not expose any method choice and default to `Cash`.
- Inactive bank account handling:
  - Vendor-side validators explicitly check company/vendor account activity.
  - Customer credit event checks only active company bank account, not full method-detail parity.
- Cleared/pending assumptions:
  - Vendor outgoing logic is effectively cleared-only.
  - Customer receipt logic supports `posted/pending/cleared/bounced`.
  - Cross-rule report logic sometimes mixes cleared-only and posted-inclusive semantics.
- Cash/bank balance divergence:
  - `get_bank_ledger()` uses transaction `date`, while other cash movement reads and dashboard metrics often use `cleared_date`.
- Refund side effects:
  - Sale return refunds are represented as negative receipts, not a separate refund table/model.

### ACC-PROB-015: Bank ledger date filter uses transaction date, not cleared date

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with code
  - Internal consistency concern
- Problem type:
  - Reporting
  - Consistency
- Evidence:
  - `database/schema.py` — `v_bank_ledger_ext` stores `sp.date`, `pp.date`, `pr.date`
  - `modules/accounting/current_rules/bank_rules.py` — `get_bank_ledger`
  - `modules/accounting/current_rules/bank_rules.py` — `get_vendor_cash_movements`, `get_customer_cash_movements`
- Why this is a problem:
  - "Bank ledger" reads a different date basis than the other cleared-cash movement functions.
- Current behavior:
  - filters and ordering are by transaction date from the source tables.
- Expected or safer behavior:
  - either use cleared date consistently for cleared-only ledgers, or document the distinction explicitly.
- Scenarios affected:
  - delayed clearing,
  - cheque deposits,
  - backdated entry with later bank clearance.
- User/business impact:
  - period bank reports can shift cash movements into the wrong window.
- Data impact:
  - reporting divergence only.
- Tests currently covering it:
  - current bank ledger tests cover row presence, not delayed-clearing date semantics.
- Missing tests:
  - one payment entered on day A and cleared on day B.
- Related rules:
  - `BANK-RULE-002`
  - `REPORT` synthesis
- Suggested later action:
  - create correction task card

### ACC-PROB-016: Customer cash-movement view treats non-cash return credit as cash inflow

- Severity: High
- Confidence: High
- Judgement basis:
  - Direct contradiction with accounting principle
  - Internal consistency concern
- Problem type:
  - Accounting correctness
  - Consistency
  - Reporting
- Evidence:
  - `modules/accounting/current_rules/bank_rules.py` — `get_customer_cash_movements`
  - query includes `customer_advances` rows where `source_type IN ('deposit', 'return_credit')`
  - vendor cash movement view does **not** include vendor `return_credit` rows
- Why this is a problem:
  - a customer return credit is a credit-note style liability to the customer, not necessarily a cash receipt.
- Current behavior:
  - positive `return_credit` appears as `Customer Credit` with direction based on amount sign.
- Expected or safer behavior:
  - return-credit rows should be excluded from cash movements unless they truly represent incoming cash.
- Scenarios affected:
  - sale returns settled as customer credit instead of refund.
- User/business impact:
  - customer cash reports can overstate cash inflow.
- Data impact:
  - read-model divergence only.
- Tests currently covering it:
  - customer cash movement tests cover receipt/refund rows, not return-credit rows.
- Missing tests:
  - customer return-credit should not appear in cash movements unless explicitly intended.
- Related rules:
  - `SAL-RULE-004`
  - `CUST-RULE-001`
- Suggested later action:
  - create correction task card

## 13. Inventory / Cost / Margin / COGS Rule Problems

| Rule ID | Trigger | Problem ID(s) | Current Behavior | Problem | Severity | Confidence | Suggested Later Action |
|---|---|---|---|---|---|---|---|
| `INV-RULE-001` | Purchase/sale inventory and return events | `ACC-PROB-003`, `ACC-PROB-008`, `ACC-PROB-020` | Inventory posting is centralized in accounting rules, but sale-return flow still has repo/UI duplication | Returnable/read logic and sale-return orchestration are not fully centralized | Medium | High | Create correction task cards |

Detailed notes:

- Purchase stock impact:
  - `record_purchase_inventory_event` looks sound from current evidence.
- Purchase return stock validation:
  - Actual write path validates stock on hand in `PUR-RULE-003`.
  - Read path `get_purchase_returnable_quantities()` is not stock-aware.
- Sale stock decrement:
  - DB trigger `trg_inventory_ref_validate` blocks sale quantity above available stock.
- Sale return stock restoration:
  - Repo still inserts sale-return inventory rows directly before calling accounting settlement.
- Margin/profit calculation:
  - `sale_financial_events` uses revenue and COGS snapshots/views and appears internally coherent.
  - downstream open-payables dashboard math is not aligned with purchase net totals after returns (`ACC-PROB-017`).
- Valuation consistency:
  - purchase/sale return snapshots are trigger-backed and should stay under characterization tests before changes.

### ACC-PROB-020: Sale return math remains duplicated outside `AccountingService`

- Severity: Medium
- Confidence: High
- Judgement basis:
  - Migration/consolidation concern
- Problem type:
  - Migration
  - Maintainability
  - Consistency
- Evidence:
  - `modules/sales/return_form.py` computes returned value directly
  - `database/repositories/sales_returns_helpers.py` computes sale returnable quantities directly
  - `database/repositories/sales_repo.py` still validates and inserts return inventory rows directly
- Why this is a problem:
  - Sale-return logic still exists in multiple places with overlapping formulas and assumptions.
- Current behavior:
  - service does not own the full sale-return rule set.
- Expected or safer behavior:
  - one source of truth for returnable quantity and settlement preview math.
- Scenarios affected:
  - UI preview vs repo/service write behavior drift.
- User/business impact:
  - higher risk of future mismatch when one path is changed and the others are not.
- Data impact:
  - future divergence risk, not a proven current corruption.
- Tests currently covering it:
  - guardrails do not scan these duplicates as accounting-rule bypasses.
- Missing tests:
  - parity tests between UI preview helpers and accounting-service preview/write outputs.
- Related rules:
  - `SAL-RULE-004`
  - `PUR-RULE-005`
- Suggested later action:
  - create correction task card

## 14. Status Rule Problems

| Rule ID | Entity | Status | Current Logic | Problem ID(s) | Severity | Confidence | Notes |
|---|---|---|---|---|---|---|---|
| `PUR-RULE-006` | Purchase | `paid` / `partial` / `unpaid` | Cleared direct payments plus applied credit compared to net purchase total | `ACC-PROB-001` | Medium | High | Different API paths expose signed vs clamped due |
| `SAL-RULE-006` | Sale | `paid` / `partial` / `unpaid` | Cleared receipts plus applied credit compared to `sale_receivable_totals.remaining_due` | `ACC-PROB-012` | High | High | Customer receivable summary does not align with canonical status semantics |
| `SAL-RULE-007` | Quotation | `draft` / `sent` / `accepted` | Conversion allowed only from `draft` or `sent` | None | High | No clear issue found |
| `CUST-RULE-004` | Customer statement period | n/a | Opening balance hard-coded to zero; dates ignored | `ACC-PROB-011` | High | High | Period semantics are effectively stale |
| `EXP` synthesis | Expense | no payment status | Immediate expense recognition only | `ACC-PROB-014` | Medium | High | Architectural risk, not a simple bug |

Status observations:

- Purchase status logic is duplicated in both DB triggers and Python service methods.
- Sale status logic is also duplicated in DB triggers and Python service methods.
- No direct bug was proven in the trigger/service status rollups themselves.
- The larger issue is that downstream summaries/reports do not always use the same basis.

## 15. Report / Display / Template Problems

| Rule ID | Consumer | Value | Problem ID(s) | Problem | Severity | Confidence | Suggested Later Action |
|---|---|---|---|---|---|---|---|
| `PUR-RULE-002` | Purchase invoice preview | Totals / remaining | `ACC-PROB-002` | Preview ignores order discount | Low | High | Verify business rule |
| `SAL-RULE-003` | Sale invoice preview | Full invoice context | `ACC-PROB-018` | Service returns only partial context | Low | High | Analyze further |
| `SAL-RULE-008`, `PUR-RULE-001` | Dashboard metrics | Open payables | `ACC-PROB-017` | Dashboard uses header totals, not net purchase totals | High | High | Create correction task card |
| `BANK-RULE-001` | Bank reports | Date windows | `ACC-PROB-015` | Bank ledger uses transaction date, not cleared date | High | High | Create correction task card |
| `CUST-RULE-004` | Customer statements | Period opening/entries | `ACC-PROB-011` | Date range ignored | High | High | Create correction task card |

Additional notes:

- `widgets/invoice_preview.py` uses purchase `preview_context`, not the canonical `context`.
- `modules/sales/controller.py` still assembles sale invoice context from multiple sources.
- Dashboard and reporting repos still contain direct SQL formulas for some historical/status metrics rather than routing every number through one accounting read model.

## 16. Cross-Rule Consistency Problems

| Problem ID | Cross-Rule Issue | Rules Involved | Severity | Confidence | Impact | Suggested Later Action |
|---|---|---|---|---|---|---|
| `ACC-PROB-001` | One purchase can have zero due in header API and negative due in another API | `PUR-RULE-001`, `PUR-RULE-006` | Medium | High | Screen/report inconsistency | Create correction task card |
| `ACC-PROB-005` | Vendor statement credit basis does not align with vendor balance basis | `VND-RULE-001`, `VND-RULE-003` | High | High | Statement underreports carried credit | Create correction task card |
| `ACC-PROB-009` + `ACC-PROB-016` | Customer-side refund/credit cash treatment differs sharply from vendor-side treatment | `SAL-RULE-004`, `CUST-RULE-001`, `BANK-RULE-002`, `VND-RULE-006` | High | High | Cash-flow reports become asymmetric | Create correction task cards |
| `ACC-PROB-012` | Customer receivable summary uses posted-inclusive math while canonical sale status/receivable logic is cleared-based | `CUST-RULE-006`, `SAL-RULE-006` | High | High | Receivable totals can disagree | Create correction task card |
| `ACC-PROB-017` | Dashboard open payables differ from purchase outstanding logic | `PUR-RULE-001`, `SAL-RULE-008`, `REPORT` synthesis | High | High | Dashboard/AP totals overstated | Create correction task card |
| `ACC-PROB-019` + `ACC-PROB-020` | Migration docs say consolidation complete, but active fallback/duplicate logic still exists | `VND-RULE-003`, `SAL-RULE-004`, `INV-RULE-001` | Medium | High | Future changes can drift | Create correction task cards |

## 17. Missing Invariants

| Invariant | Area | Currently Enforced? | Tested? | Evidence | Risk | Suggested Later Action |
|---|---|---|---|---|---|---|
| Payment/credit presentation should use one signed/clamped convention per entity | Purchase | No | Partial | `get_purchase_financials` vs `get_purchase_outstanding` | Medium | Define and test invariant |
| Supplier refund totals should not exceed unresolved refundable return value | Vendor / Purchase | No | No | `record_supplier_refund_event` has no amount cap | High | Add correction task card |
| Customer statement dates should filter entries and opening balance | Customer | No | No | `get_customer_statement` ignores dates | High | Add correction task card |
| Receivable summaries should align with canonical cleared-based sale receivables | Customer / Sales | No | No | `get_customer_receivable_summary` subtracts posted payments | High | Add correction task card |
| Bank-ledger date basis should be explicit and consistent | Bank | No | No | `v_bank_ledger_ext` uses `date`, not `cleared_date` | High | Add correction task card |
| Customer return credit should not appear as cash inflow unless explicitly intended | Bank / Sales / Customer | No | No | `get_customer_cash_movements` includes `return_credit` | High | Add correction task card |
| Dashboard payables should match canonical purchase outstanding totals | Reports | No | No | dashboard SQL uses `p.total_amount` not `purchase_detailed_totals` | High | Add correction task card |
| Public accounting writes should not depend on wrapper-only validation | Customer | No | Partial | repo wrapper stronger than service write path | Medium | Consolidate validation |
| Guardrail tests should catch relative imports of accounting internals | Migration | No | No | `modules/vendor/controller.py` relative import bypasses prefix match | Medium | Tighten guardrail tests |

## 18. Missing / Weak Test Coverage

| Area | Rule ID | Missing Test | Why It Matters | Suggested Test Name | Priority |
|---|---|---|---|---|---|
| purchase | `PUR-RULE-001` | Compare all outstanding APIs in one overpayment scenario | Locks sign/clamp policy | `test_purchase_outstanding_api_conventions_match_documented_policy` | High |
| purchase | `PUR-RULE-005` | Returnable quantity vs depleted stock | Prevent misleading UI behavior | `test_purchase_returnable_qty_can_exceed_stock_but_write_path_blocks` | Medium |
| purchase | `PUR-RULE-006` | Dedicated payment-history coverage | Current docs overstate coverage | `test_purchase_payment_history_order_and_metadata` | Low |
| vendor | `VND-RULE-003` | Opening statement with carried return credit | Statement may understate credit | `test_vendor_statement_opening_credit_includes_return_credit_balance` | High |
| vendor | `VND-RULE-006` | Direct refund above return value | Over-refund currently allowed | `test_supplier_refund_rejects_amount_above_unsettled_return_value` | High |
| sales | `SAL-RULE-004` | Refund-by-bank policy or explicit cash-only policy | Current API forces cash-only | `test_sale_return_refund_method_policy_is_explicit` | High |
| sales | `SAL-RULE-005` | Repo-path cleared overpayment conversion | Current repo passes bad customer id | `test_sale_payments_repo_overpayment_uses_sale_customer_id` | Critical |
| customer | `CUST-RULE-004` | Date-bounded customer statement with opening balance | Current API ignores dates | `test_customer_statement_filters_period_and_computes_opening_balance` | High |
| customer | `CUST-RULE-006` | Posted vs cleared receivable summary | Current summary undercuts canonical due | `test_customer_receivable_summary_ignores_posted_uncleared_payments` | High |
| expense | `EXP-RULE-001` | Explicit acceptance of expense no-bank-link model | Architectural risk is untested/undocumented | `test_expense_model_no_cash_link_is_documented_behavior` | Medium |
| bank/cash | `BANK-RULE-001` | Delayed clearing date window | Current ledger uses wrong date basis for some consumers | `test_bank_ledger_filters_on_intended_date_basis` | High |
| bank/cash | `BANK-RULE-002` | Return credit excluded from customer cash movements | Prevent false cash inflows | `test_customer_cash_movements_exclude_non_cash_return_credit` | High |
| inventory/COGS | `INV-RULE-001` | UI/helper parity with accounting return math | Duplicate logic can drift | `test_sale_return_helpers_match_accounting_service_math` | Medium |
| reports/status | `REPORT` synthesis | Dashboard payables after purchase return | Current dashboard diverges | `test_dashboard_open_payables_match_purchase_outstanding_after_returns` | High |

## 19. Potential Data Integrity Risks

| Risk | Area | Files/Functions | Scenario | Impact | Severity | Suggested Later Action |
|---|---|---|---|---|---|---|
| Overpayment credit created for customer `0` | Sales / Customer credit | `database/repositories/sale_payments_repo.py`, `modules/accounting/current_rules/sales_rules.py::_handle_overpayment` | Cleared overpayment recorded through repo | Credit mis-post or transaction failure | Critical | Create correction task card immediately |
| Supplier refunds not capped to unresolved return value | Vendor / Purchase | `modules/accounting/current_rules/vendor_rules.py::record_supplier_refund_event` | Repeated/manual refund entry | Over-refund history | High | Create correction task card |
| Bank rows for vendor overpayment credit lack account metadata | Vendor / Bank | `modules/accounting/current_rules/vendor_rules.py::_record_vendor_deposit_credit` | Bank-method overpayment | Hard-to-reconcile bank outflow | Medium | Create correction task card |
| Date-bounded customer statement silently ignores range | Customer | `modules/accounting/current_rules/customer_rules.py::get_customer_statement` | Statement for one month | Misleading statement exports | High | Create correction task card |
| Posted payments reduce customer summary due before clearing | Customer / Sales | `modules/accounting/current_rules/customer_rules.py::get_customer_receivable_summary` | Pending settlement lag | Understated receivables | High | Create correction task card |
| Dashboard open payables bypass canonical purchase net totals | Reports | `modules/accounting/current_rules/sales_rules.py::get_sales_dashboard_metrics`, `database/repositories/dashboard_repo.py::summary_metrics` | Purchase returns exist | AP dashboard overstatement | High | Create correction task card |
| Guardrail audit misses relative internal import | Migration | `modules/vendor/controller.py`, `tests/accounting/test_vendor_purchase_accounting_guardrails.py` | Future refactor assumes guardrails are strict | Hidden bypass remains active | Medium | Tighten guardrail tests later |

## 20. Problem Prioritization

### Must Fix First

- `ACC-PROB-010` — `SAL-RULE-005`: repo overpayment path uses `customer_id=0`.
- `ACC-PROB-007` — `VND-RULE-006`: supplier refunds are not capped to refundable return value.
- `ACC-PROB-005` — `VND-RULE-003`: vendor statement opening credit excludes return-credit carry-forward.
- `ACC-PROB-011` — `CUST-RULE-004`: customer statement ignores date range and opening balance.
- `ACC-PROB-012` — `CUST-RULE-006`: receivable summary reduces due using posted payments.
- `ACC-PROB-015` — `BANK-RULE-001`: bank ledger uses transaction date instead of cleared date.
- `ACC-PROB-016` — `BANK-RULE-002`: customer return credit appears as cash inflow.
- `ACC-PROB-017` — dashboard/report synthesis: open payables ignore purchase returns.

### Fix Soon

- `ACC-PROB-001` — `PUR-RULE-001`: purchase outstanding sign/clamp inconsistency.
- `ACC-PROB-003` — `PUR-RULE-005`: returnable quantity helper ignores stock-on-hand.
- `ACC-PROB-006` — `VND-RULE-002`: vendor overpayment credit loses bank metadata.
- `ACC-PROB-008` — `SAL-RULE-004`: sale return rule is only partially consolidated.
- `ACC-PROB-009` — `SAL-RULE-004`: sale refund path is cash-only and lacks bank metadata.
- `ACC-PROB-013` — `CUST-RULE-001`: customer credit event lacks full method-detail validation.
- `ACC-PROB-014` — `EXP-RULE-001`/`003`/`004`: expenses have no bank/cash linkage model.
- `ACC-PROB-019` — `VND-RULE-003`: migration guardrail blind spot.
- `ACC-PROB-020` — `SAL-RULE-004`/`INV-RULE-001`: sale-return math still duplicated outside accounting service.

### Fix Later

- `ACC-PROB-002` — `PUR-RULE-002`: purchase invoice preview discount fallback.
- `ACC-PROB-004` — `PUR-RULE-006`: docs cite nonexistent payment-history test.
- `ACC-PROB-018` — `SAL-RULE-003`: sale invoice-financials facade is only partial.

### Needs Investigation

- `PUR-RULE-003`: settlement formula and side effects should stay under characterization tests before any change.
- `SAL-RULE-006`: status/reversal behavior is complex and partly trigger-driven; no direct contradiction was proven, but it is high-risk for future edits.
- `EXP-RULE-003` / `EXP-RULE-004`: expense no-bank-link model may be acceptable for product scope, but that needs an explicit business decision.

## 21. Recommended Next Step

Next step should be:
- review this analysis with product/accounting owners,
- decide which items are true corrections vs accepted current behavior,
- then create TDD-based correction task cards ordered by financial risk,
- start with the Critical/High items that can distort receivables, payables, bank reports, or statements.

Do not create correction task cards until this analysis is reviewed and accepted.

## 22. Final Confirmation

- No production code changed.
- No tests were added.
- No test commands were run.
- No schema or migration changes were made.
- No UI behavior was changed.
- This file is analysis only.
