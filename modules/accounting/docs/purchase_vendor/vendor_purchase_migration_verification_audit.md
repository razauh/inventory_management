# Vendor + Purchase Migration Verification Audit Report

## 1. Scope & Purpose

This audit report verifies the completeness and correctness of the Vendor + Purchase accounting consolidation into the central `AccountingService` facade located in `modules/accounting/`. The goal of the consolidation was to route all accounting-related calculations, database updates, and state reads for vendors and purchases through a single public facade, separating the accounting layer from the business/UI layers while preserving existing behavior.

## 2. Task Cards Verification Status

All task cards (VP-ACC-001 through VP-ACC-021) defined for the Vendor + Purchase consolidation have been verified against the current codebase:

| Task Card | Title | Verification Status | Notes |
|---|---|---|---|
| **VP-ACC-001** | Verify scaffold and public accounting facade rules | **COMPLETED** | Service facade and rules modules structure established. |
| **VP-ACC-002** | Define Vendor + Purchase accounting DTO/API contracts | **COMPLETED** | Contracts and DTOs defined in `modules/accounting/dto.py` and exported. |
| **VP-ACC-003** | Consolidate purchase totals and discount calculations | **COMPLETED** | Implemented and routed through `AccountingService.get_purchase_totals`. |
| **VP-ACC-004** | Consolidate purchase outstanding/payable calculations | **COMPLETED** | Implemented and routed through `AccountingService.get_purchase_outstanding`. |
| **VP-ACC-005** | Consolidate purchase payment status calculations | **COMPLETED** | Routed through `AccountingService.get_purchase_payment_status` / `recalculate_purchase_payment_status`. |
| **VP-ACC-006** | Consolidate vendor advance/credit balance calculations | **COMPLETED** | Routed through `AccountingService.get_vendor_advance_balance`. |
| **VP-ACC-007** | Consolidate vendor purchase totals and open purchase reads | **COMPLETED** | Routed through `AccountingService.get_vendor_purchase_totals`. |
| **VP-ACC-008** | Consolidate vendor statement/history read model | **COMPLETED** | Routed through `AccountingService.get_vendor_statement`. |
| **VP-ACC-009** | Consolidate purchase payment summary read model | **COMPLETED** | Routed through `AccountingService.get_purchase_payment_summary`. |
| **VP-ACC-010** | Consolidate vendor payment metadata validation | **COMPLETED** | Routed through `AccountingService.validate_vendor_payment_metadata`. |
| **VP-ACC-011** | Consolidate vendor payment current write behavior | **COMPLETED** | Routed through `AccountingService.record_vendor_payment_event`. |
| **VP-ACC-012** | Consolidate vendor advance/deposit current write behavior | **COMPLETED** | Routed through `AccountingService.record_vendor_advance_event`. |
| **VP-ACC-013** | Consolidate vendor credit application behavior | **COMPLETED** | Routed through `AccountingService.record_vendor_credit_application`. |
| **VP-ACC-014** | Consolidate advance allocation/FIFO behavior | **COMPLETED** | Routed through `AccountingService.preview_vendor_advance_allocation` and `record_vendor_advance_event`. |
| **VP-ACC-015** | Consolidate purchase return valuation calculations | **COMPLETED** | Routed through `AccountingService.get_purchase_return_values` and `get_purchase_return_totals`. |
| **VP-ACC-016** | Consolidate purchase return settlement behavior | **COMPLETED** | Routed through `AccountingService.record_purchase_return_event`. |
| **VP-ACC-017** | Consolidate supplier refund behavior | **COMPLETED** | Routed through `AccountingService.record_supplier_refund_event`. |
| **VP-ACC-018** | Consolidate bank/cash movement read behavior | **COMPLETED** | Routed through `AccountingService.get_vendor_cash_movements`. |
| **VP-ACC-019** | Consolidate inventory effects from purchases and returns | **COMPLETED** | Routed through `AccountingService.record_purchase_inventory_event` and `record_purchase_return_event`. |
| **VP-ACC-020** | Consolidate invoice/template/report financial value sourcing | **COMPLETED** | Sourced via `AccountingService.get_purchase_invoice_financials` and report adapters. |
| **VP-ACC-021** | Cleanup migrated calculations and enforce guardrails | **COMPLETED** | Bypasses removed. Guardrails test verifying all imports and call sites passes. |

## 3. Wiring and Guardrails Validation

A rigorous check of call sites has been conducted to confirm that no external modules import internal rules directly, and all migrated accounting slices route exclusively through `AccountingService`.

The automated guardrail test `tests/accounting/test_vendor_purchase_accounting_guardrails.py` verified the following call-site routing:
* **Purchases Repository (`database/repositories/purchases_repo.py`)**: Routes all purchase totals, outstanding amounts, returns, return values, inventory events, and returnable quantities through `self.accounting`.
* **Purchase Payments Repository (`database/repositories/purchase_payments_repo.py`)**: Routes payment event recording through `AccountingService.record_vendor_payment_event`.
* **Vendor Advances Repository (`database/repositories/vendor_advances_repo.py`)**: Routes outstanding due checks and advance event recording through `self.accounting`.
* **Purchase Controller (`modules/purchase/controller.py`)**: Sourced through the service for invoice financials, payment summaries, payment events, and returns.
* **Return Form (`modules/purchase/return_form.py`)**: Uses the service to get purchase financials and preview return effects.
* **Reporting Module (`modules/reporting/`)**: Sourced through `AccountingService` for AP summary, vendor aging, and payment/disbursement activities.
* **Invoice Preview Widget (`widgets/invoice_preview.py`)**: Sourced through `AccountingService` for purchase invoice financials.

Imports of `modules.accounting.current_rules` or `modules.accounting.ledger` are strictly restricted to the `modules/accounting/` directory itself. No external files contain direct imports of these packages, satisfying the architectural isolation requirement.

## 4. Test Suite and Coverage Summary

All verification tests for the consolidated accounting logic pass successfully:

* **Guardrail Tests (`tests/accounting/test_vendor_purchase_accounting_guardrails.py`)**: **4/4 PASSED**. Confirms facade isolation, API structure, and call-site rewiring correctness.
* **Consolidated Accounting Contract & Unit Tests (`tests/accounting/`)**: **40/40 PASSED**. Covers contracts, DTO configurations, balance logic, cash movements, inventory updates, and returning calculations.
* **Vendor & Purchase Integration Suite (`tests/vendor/`, `tests/purchase/`)**: **291/291 PASSED**. Verifies that no behavioral regressions were introduced to vendor advances, purchase payment records, active company/vendor bank validation, return snapshots, return settlements, or vendor updates.
* **Reporting Suite (`tests/reporting/`)**: **22/22 PASSED**. Verifies that reporting outputs (aging cutoff, net totals, disbursements) remain correct and match historical calculations.

## 5. Patches Applied

* **None Required**: The existing wiring, scaffolding, and integration code were found to be completely correct and fully compliant with the task cards. All call sites were successfully rewired in the prior step, and guardrail tests pass with no regressions.

## 6. Deferred Accounting Correctness Issues

Per repository guardrails, the migration preserved legacy behavior and deferred any business rule corrections. The following existing issues were documented and preserved:
1. **Invoice Preview Discount Fallback**: Resolved in `ACC-FIX-002`. The preview now matches the canonical totals and displays active order discounts.
2. **Double-Entry Ledgers**: No double-entry ledger database tables have been introduced yet. Calculations remain read-model aggregations over current transaction tables.
3. **Database Triggers vs. Repository Status Logic**: The payment status rollup logic (`paid`, `unpaid`, `partial`) is computed both by database triggers (`trg_paid_from_purchase_payments_*`) and by repository/service Python methods (`recalculate_purchase_payment_status`). Both systems were preserved to prevent integrity violations.
4. **Cleared-Only Payment Assumption**: All payment and advance logic assumes that only cleared payments are processed; pending or bounced lifecycles are rejected.

## 7. Duplicate Calculation Check

* No duplicate accounting calculations exist in the `modules/vendor`, `modules/purchase`, or `database/repositories/` modules that bypass the `AccountingService`. All balance queries, outstanding balance checks, payment records, return settlements, and reporting reads route directly through `AccountingService`.

## 8. Final Completion Status

* **Status**: **MIGRATION VERIFIED AND COMPLETE**
* All vendor and purchase accounting logic has been successfully consolidated under `modules/accounting/service.py` (`AccountingService`).
