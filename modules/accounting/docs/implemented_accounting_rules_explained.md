# Implemented Accounting Rules Explained

## 1. Purpose
This document provides a detailed, human-readable explanation of how the currently implemented accounting rules work in the inventory management system. 

Please note:
- **This is not a correctness review**: It documents what is currently implemented, not what should be.
- **This is not a correction plan**: No code changes or database migrations are proposed or executed here.
- **This does not claim the rules are final**: These rules represent the current snapshot of the migrated modules.
- **This explains currently implemented behavior only**: To help developers, auditors, and business users understand the exact mechanics of the application without digging into source code.
- **Possible issues are documented for later review**: Any anomalies, asymmetry, or risks found during static inspection are highlighted under the "Possible later correctness review" subheadings.

---

## 2. Source Documents and Code Inspected
The following files and folders were systematically inspected to compile these explanations:
- **Source Index**: `/media/pc/64B0D1DBB0D1B3B0/inventory_management/modules/accounting/docs/implemented_accounting_rules_reference.md`
- **Accounting Facade**: `modules/accounting/service.py`
- **Accounting Current Rules**:
  - `modules/accounting/current_rules/purchase_rules.py`
  - `modules/accounting/current_rules/vendor_rules.py`
  - `modules/accounting/current_rules/sales_rules.py`
  - `modules/accounting/current_rules/customer_rules.py`
  - `modules/accounting/current_rules/expense_rules.py`
  - `modules/accounting/current_rules/inventory_rules.py`
  - `modules/accounting/current_rules/bank_rules.py`
- **Accounting Validation & Schema**:
  - `modules/accounting/validators.py`
  - `database/schema.py`
- **Domain Modules**:
  - `modules/purchase/`, `modules/vendor/`, `modules/sales/`, `modules/customer/`, `modules/expense/`
- **Tests Suite**:
  - `tests/accounting/` (all 45 test scripts)

---

## 3. Explanation Standard Used
Every single rule in this document is expanded using the following 14-point template:
1. **Plain-English explanation**: Plain-language summary of what the rule does.
2. **Why this rule exists in the application**: Business or functional purpose.
3. **When this rule runs**: Specific triggers or user actions that initiate execution.
4. **Full implementation flow**: Chronological step-by-step flow from triggers to return values.
5. **Inputs used**: Fields and database tables read.
6. **Outputs produced**: DTOs, values, and return structures.
7. **Calculation details**: Mathematical formulas, factors, and logic gates.
8. **Constraints and validations**: Pre-conditions, limits, and validation checks.
9. **Data read**: Database tables and views queried.
10. **Data written or side effects**: Table mutations, status adjustments, and downstream effects.
11. **Edge cases handled**: Handled conditions.
12. **Edge cases not clearly handled**: Missing validations or untested behaviors.
13. **Example scenario**: Numerical or procedural scenario.
14. **References**: Exact paths for implementation, consumers, tests, and call sites.

---

## 4. Rule Reading Guide
- **"Current behavior"**: Refers strictly to the active logic found in the code workspace.
- **"Constraint"**: Conditions enforced by Python validation or SQLite constraints.
- **"Side effect"**: Writes or state changes that occur downstream of a method call (e.g. updating payment statuses).
- **"Possible later correctness review"**: Notes pointing out design inconsistencies or risks to inspect during a future correctness phase.

---

## 5. Purchase Rules Explained

### PUR-RULE-001: Purchase Financials Aggregation

#### Plain-English explanation
This rule calculates all financial totals for a purchase order: the initial net cost, how much cash has been paid directly, how much pre-paid advance was applied, the total value of returned products, and what outstanding amount remains to be paid to the vendor.

#### Why this rule exists in the application
It provides the core unpaid liability context for any purchase, enabling payment tracking and preventing double-paying a vendor.

#### When this rule runs
- When viewing a purchase order.
- Before logging a new vendor payment.
- During statement generation or outstanding balance updates.

#### Full implementation flow
```text
User views purchase
→ AccountingService.get_purchase_financials()
→ purchase_rules.get_purchase_financials()
→ Queries purchases, purchase_detailed_totals, and purchase_payments
→ Sums cleared payments and applies advance allocations
→ Computes outstanding balance
→ Returns PurchaseFinancials DTO
```

#### Inputs used
- `purchase_id` (int | str)
- Database rows in `purchases`, `purchase_detailed_totals`, `purchase_payments`

#### Outputs produced
`PurchaseFinancials` DTO containing:
- `purchase_id`, `net_total`, `paid_amount`, `applied_advances`, `returned_value`, `cleared_direct_payments`, `prior_refunds`, `outstanding_balance`.

#### Calculation details
- `cleared_direct_payments` = Sum of all cleared direct payments in `purchase_payments`.
- `paid_amount` = `cleared_direct_payments` + `applied_advances` - `prior_refunds`.
- `outstanding_balance` = `net_total` - `paid_amount`.

#### Constraints and validations
- The purchase must exist in the database.

#### Data read
- Views: `purchase_detailed_totals`
- Tables: `purchases`, `purchase_payments`

#### Data written or side effects
None (read-only query).

#### Edge cases handled
- Handles cases where no payments or return records exist (returns default `Decimal("0")`).

#### Edge cases not clearly handled
- Direct column mutation of `purchases.paid_amount` bypassing `purchase_payments` records will cause remaining due calculations to mismatch.

#### Example scenario
```text
Purchase net total = 1,000
Cleared direct payment = 400
Applied advance = 100
Returned value = 50
Outstanding balance = 1,000 - (400 + 100) = 500
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_financials`
- Facade: `modules/accounting/service.py` — `AccountingService.get_purchase_financials`

#### Original call-site references
- `modules/purchase/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_outstanding.py` — `test_purchase_outstanding_matches_repo_remaining_due`

#### Confidence
High.

#### Possible later correctness review
- In-memory modifications of the paid amount columns outside of the payment ledger can lead to total mismatches.

---

### PUR-RULE-002: Purchase Invoice Financials Context

#### Plain-English explanation
This rule builds the detailed print layout metadata for a purchase invoice, including vendor contact details, item-by-item discounts, running order totals, and a chronological history of payment receipts.

#### Why this rule exists in the application
To produce the exact line items, tax details, and transaction history for PDF templates and print previews.

#### When this rule runs
- When generating invoice print layouts.
- When loading invoice detail views.

#### Full implementation flow
```text
Print Invoice request
→ AccountingService.get_purchase_invoice_financials()
→ purchase_rules.get_purchase_invoice_financials()
→ Reads vendor, item lines, discounts, and payments
→ Combines data into a dictionary structure
→ Returns PurchaseInvoiceFinancials DTO
```

#### Inputs used
- `purchase_id` (int | str)

#### Outputs produced
`PurchaseInvoiceFinancials` DTO containing detailed line arrays and address strings.

#### Calculation details
- Subtotal discount allocations are computed per item line.
- Net line total = `quantity * (purchase_price - item_discount)`.

#### Constraints and validations
- Purchase ID must correspond to a valid row.

#### Data read
- Tables: `purchases`, `purchase_items`, `vendors`, `purchase_payments`

#### Data written or side effects
None.

#### Edge cases handled
- Gracefully formats missing contact fields or notes as empty strings rather than raising errors.

#### Edge cases not clearly handled
- Handling of multiple tax brackets or surcharge overrides is not supported.

#### Example scenario
```text
Item A: 10 units @ $10, line discount $1. Net line total = $90.
Total invoice subtotal = $90.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_invoice_financials`
- Facade: `modules/accounting/service.py` — `AccountingService.get_purchase_invoice_financials`

#### Original call-site references
- `modules/purchase/invoice_preview.py`

#### Test references
- `tests/accounting/test_vendor_purchase_invoice_financials.py`

#### Confidence
High.

#### Possible later correctness review
- Ensure item discounts are not double counted when order-level discounts are also applied.

---

### PUR-RULE-003: Purchase Return Event Processing

#### Plain-English explanation
This rule processes a product return back to a vendor. It verifies that we have enough inventory in stock to return, calculates the return value (factoring in any purchase-level discounts), determines the settlement amount, and registers the refund either as cash or a vendor advance credit.

#### Why this rule exists in the application
To adjust inventory counts, reverse purchases, record vendor credits, and maintain double-entry accuracy when items are returned.

#### When this rule runs
- When a user submits a purchase return form.

#### Full implementation flow
```text
Submit return form
→ AccountingService.record_purchase_return_event()
→ purchase_rules.record_purchase_return_event()
→ Checks stock via v_stock_on_hand
→ Inserts return snapshots
→ Records vendor advance credit or supplier refund
→ Triggers inventory transactions
→ Updates payment status
```

#### Inputs used
- `payload: PurchaseReturnPayload` (includes purchase ID, lines to return, quantities, settlement details)

#### Outputs produced
`PurchaseReturnResult` DTO showing:
- `purchase_id`, `transaction_ids`, `return_value`, `settlement_amount`

#### Calculation details
- `return_value_factor` = `(subtotal - order_discount) / subtotal`.
- `settlement_amount` = `funded_amount - post_return_total - prior_settlements`.

#### Constraints and validations
- Return quantity cannot exceed original purchase quantity minus prior returns.
- Return quantity cannot exceed current base unit stock on hand.
- "Refund Now" settlement requires a fully settled purchase (remaining due must be 0).

#### Data read
- Views: `v_stock_on_hand`, `purchase_detailed_totals`
- Tables: `purchases`, `purchase_items`, `purchase_payments`, `vendor_advances`, `purchase_refunds`

#### Data written or side effects
- Writes to `inventory_transactions`
- Writes to `customer_advances` or `purchase_payments`
- Updates `purchases.payment_status`

#### Edge cases handled
- Rejects returns that would drop base unit stock below zero.

#### Edge cases not clearly handled
- If physical inventory was adjusted manually in between, validation fails even if the purchase return is legitimate.

#### Example scenario
```text
Purchase cost = $1,000, fully paid.
Return item value = $200.
Post-return purchase value = $800.
Settlement amount = $1,000 - $800 = $200 (created as refund/advance).
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/purchase_rules.py` — `record_purchase_return_event`

#### Original call-site references
- `modules/purchase/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_return_event.py`

#### Confidence
High.

#### Possible later correctness review
- Evaluate whether returning items should allow partial cash refund and partial credit note split in a single transaction.

---

### PUR-RULE-004: Purchase Return Totals

#### Plain-English explanation
This rule sums up the total quantities and monetary values of all returned items for a specific purchase.

#### Why this rule exists in the application
To display total return metrics on purchase dashboards and list views.

#### When this rule runs
- When loading purchase summaries.

#### Full implementation flow
```text
Load summary
→ AccountingService.get_purchase_return_totals()
→ purchase_rules.get_purchase_return_totals()
→ Queries purchase_return_values view
→ Sums quantities and value
→ Returns PurchaseReturnTotals DTO
```

#### Inputs used
- `purchase_id`

#### Outputs produced
`PurchaseReturnTotals` DTO containing `qty` (Decimal) and `value` (Decimal).

#### Calculation details
- `qty` = Sum of all `qty_returned`.
- `value` = Sum of all `return_value`.

#### Constraints and validations
None.

#### Data read
- View: `purchase_return_valuations`

#### Data written or side effects
None.

#### Edge cases handled
- Returns 0 quantities and values if no returns exist.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Return A: 5 units value $50.
Return B: 2 units value $20.
Total quantity = 7, total value = $70.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_return_totals`

#### Original call-site references
- `modules/purchase/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_return_valuation.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### PUR-RULE-005: Purchase Returnable Quantities

#### Plain-English explanation
This rule calculates how many units of each item in a purchase can still be returned, based on the original purchase quantity and any units returned in the past.

#### Why this rule exists in the application
To cap returns and prevent returning more items than were originally purchased.

#### When this rule runs
- When opening a purchase return screen to populate maximum return bounds.

#### Full implementation flow
```text
Open return screen
→ AccountingService.get_purchase_returnable_quantities()
→ inventory_rules.get_purchase_returnable_quantities()
→ Queries purchase line quantities and subtracts sum of prior returns
→ Returns dictionary mapping item IDs to remaining returnable quantities
```

#### Inputs used
- `purchase_id`

#### Outputs produced
`dict[int, Decimal]` (item_id -> remaining_qty)

#### Calculation details
- `remaining_qty` = `purchase_qty` - `sum(returned_qty)`.

#### Constraints and validations
- Purchase ID must be valid.

#### Data read
- Tables: `purchase_items`, `inventory_transactions`

#### Data written or side effects
None.

#### Edge cases handled
- Items with zero remaining quantities are mapped to `Decimal("0")`.

#### Edge cases not clearly handled
- Does not verify if items are currently active or discontinued.

#### Example scenario
```text
Purchased Quantity = 10.
Returned in prior transaction = 3.
Remaining returnable quantity = 7.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/inventory_rules.py` — `get_purchase_returnable_quantities`

#### Original call-site references
- `modules/purchase/ui_return.py`

#### Test references
- `tests/accounting/test_vendor_purchase_return_valuation.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### PUR-RULE-006: Purchase Payment History & Summary

#### Plain-English explanation
This rule retrieves the full payment history for a purchase and summarizes payment states (such as direct payments and excess overpayments converted to credit).

#### Why this rule exists in the application
To show payment history tables and verify the overall payment status of a purchase.

#### When this rule runs
- When viewing the payment history tab of a purchase order.

#### Full implementation flow
```text
Load payment history tab
→ AccountingService.get_purchase_payment_history()
→ purchase_rules.get_purchase_payment_history()
→ Fetches purchase_payments records ordered by date
→ Returns tuple of PurchasePaymentRow DTOs
```

#### Inputs used
- `purchase_id`

#### Outputs produced
Tuple of `PurchasePaymentRow` DTOs and `PurchasePaymentSummary` DTO.

#### Calculation details
Sums up all direct payments and overpayments.

#### Constraints and validations
None.

#### Data read
- Tables: `purchase_payments`, `company_bank_accounts`, `vendor_bank_accounts`

#### Data written or side effects
None.

#### Edge cases handled
- Handles cases where no payments have been recorded yet.

#### Edge cases not clearly handled
None.

#### Example scenario
- Returns list of checks and bank transfers associated with purchase order #10.

#### Implementation references
- Implementation: `modules/accounting/current_rules/purchase_rules.py` — `get_purchase_payment_history`

#### Original call-site references
- `modules/purchase/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_payment_summary.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

## 6. Vendor Rules Explained

### VND-RULE-001: Vendor Advance Credit

#### Plain-English explanation
This rule records a credit balance/advance for a vendor. This advance can arise from a direct deposit or from a return credit, and it is recorded against the vendor's profile to be applied to future purchases.

#### Why this rule exists in the application
To track pre-payments, credit notes, and deposit balances outstanding with suppliers.

#### When this rule runs
- When saving a purchase return settled via vendor credit.
- When recording a direct advance payment to a supplier.

#### Full implementation flow
```text
Log advance credit
→ AccountingService.record_vendor_advance_event()
→ vendor_rules.record_vendor_advance_event()
→ Validates bank account details
→ Inserts record into vendor_advances table
→ Returns VendorAdvanceResult DTO
```

#### Inputs used
- `payload: VendorAdvancePayload` (vendor ID, amount, type, date, bank info)

#### Outputs produced
`VendorAdvanceResult` DTO.

#### Calculation details
Increments the vendor's advance credit ledger.

#### Constraints and validations
- Bank account must be active (if bank account ID is provided).
- Vendor ID must exist.

#### Data read
- Tables: `vendors`, `company_bank_accounts`

#### Data written or side effects
- Writes to `vendor_advances`

#### Edge cases handled
- Rejects transaction if the selected bank account is marked inactive.

#### Edge cases not clearly handled
- Does not check if the advance date is in the future.

#### Example scenario
```text
Record deposit of $500 to Vendor X.
Writes $500 to vendor_advances table.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/vendor_rules.py` — `record_vendor_advance_event`

#### Original call-site references
- `modules/vendor/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_vendor_advance_event.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### VND-RULE-002: Vendor Payment Processing

#### Plain-English explanation
This rule records a check or cash payment made to a vendor for a purchase. If the payment amount exceeds what is currently owed, the extra amount is converted into a vendor advance credit.

#### Why this rule exists in the application
To pay purchase orders and handle overpayments without losing track of excess funds.

#### When this rule runs
- When logging a vendor payment.

#### Full implementation flow
```text
Submit payment
→ AccountingService.record_vendor_payment_event()
→ vendor_rules.record_vendor_payment_event()
→ Computes outstanding balance
→ If payment > outstanding, logs excess in vendor_advances
→ Inserts payment row into purchase_payments
→ Recalculates purchase payment status
```

#### Inputs used
- `payload: VendorPaymentPayload`

#### Outputs produced
`VendorPaymentResult` DTO.

#### Calculation details
- `excess` = `payment_amount` - `outstanding_balance`.
- If `excess > 0`, writes `excess` to `vendor_advances`.

#### Constraints and validations
- Payment amount must be positive.
- Bank accounts must be active.

#### Data read
- Tables: `purchases`, `purchase_payments`, `company_bank_accounts`

#### Data written or side effects
- Writes to `purchase_payments`
- Writes to `vendor_advances` (on overpayment)
- Updates `purchases.paid_amount` and `purchases.payment_status`

#### Edge cases handled
- Excess payments are automatically converted to credit notes.

#### Edge cases not clearly handled
- If payment is in "pending" status, excess is not converted until it clears.

#### Example scenario
```text
Outstanding balance = $400.
Cleared payment submitted = $500.
Payment recorded = $400.
Vendor advance logged = $100.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/vendor_rules.py` — `record_vendor_payment_event`

#### Original call-site references
- `modules/vendor/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_vendor_payment_event.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### VND-RULE-003: Vendor Statement Generation

#### Plain-English explanation
This rule compiles a complete chronological timeline of transactions for a vendor, showing purchases, cash payments, returns, advances, and credits to calculate a running payable balance.

#### Why this rule exists in the application
To generate statements of account for suppliers to reconcile invoices and payments.

#### When this rule runs
- When generating vendor statements or running aging reports.

#### Full implementation flow
```text
Request statement
→ AccountingService.get_vendor_statement()
→ vendor_rules.get_vendor_statement()
→ Pulls purchases, payments, returns, and advances
→ Sorts chronologically
→ Computes running balance
→ Returns statement dictionary
```

#### Inputs used
- `vendor_id`, `date_from`, `date_to`

#### Outputs produced
Dictionary containing statement lines and balances.

#### Calculation details
Running Balance = `Previous Balance` + `Purchase Amount` - `Payments` - `Credits` + `Refunds`.

#### Constraints and validations
- Vendor must exist.

#### Data read
- Tables: `purchases`, `purchase_payments`, `purchase_refunds`, `vendor_advances`

#### Data written or side effects
None.

#### Edge cases handled
- Computes opening balances for periods starting after the first transaction.

#### Edge cases not clearly handled
- Statement ignores uncleared payments entirely.

#### Example scenario
```text
Opening balance = $0.
Purchase = $1,000. Running payable = $1,000.
Payment = $600. Running payable = $400.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/vendor_rules.py` — `get_vendor_statement`

#### Original call-site references
- `modules/vendor/reports.py`

#### Test references
- `tests/accounting/test_vendor_purchase_vendor_statement.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### VND-RULE-004: Vendor Credit Allocation (FIFO Auto-Apply)

#### Plain-English explanation
This rule automatically takes unapplied vendor credits (from deposits or return credits) and applies them to outstanding purchases chronologically using FIFO (First-In, First-Out).

#### Why this rule exists in the application
To automatically pay off oldest bills when new credit notes are created.

#### When this rule runs
- When applying vendor advances.

#### Full implementation flow
```text
Apply advance
→ AccountingService.record_vendor_advance_with_auto_apply()
→ vendor_rules.record_vendor_advance_with_auto_apply()
→ Fetches open purchases ordered by date
→ Allocates advance amount to oldest outstanding purchase first
→ Inserts credit application records
→ Updates purchase paid amounts
```

#### Inputs used
- `vendor_id`, `amount`

#### Outputs produced
Dictionary summarizing allocated amounts.

#### Calculation details
Loops through purchases, applying credit until credit is depleted or outstanding due reaches zero.

#### Constraints and validations
- Advance credit must be available.

#### Data read
- Tables: `purchases`, `vendor_advances`

#### Data written or side effects
- Writes to `purchase_credit_applications`
- Updates `purchases.paid_amount`

#### Edge cases handled
- Partial allocations are handled correctly.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Purchase 1 (Jan 1) outstanding = $300.
Purchase 2 (Jan 5) outstanding = $500.
Vendor credit applied = $400.
Purchase 1 becomes fully paid (allocates $300).
Purchase 2 gets $100 allocated, remaining outstanding = $400.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/vendor_rules.py` — `record_vendor_advance_with_auto_apply`

#### Original call-site references
- `modules/vendor/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_advance_allocation.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### VND-RULE-005: Vendor Open Purchases

#### Plain-English explanation
This rule lists all purchase orders for a vendor that still have an outstanding unpaid balance greater than zero.

#### Why this rule exists in the application
To show open invoices when allocating payments or credits.

#### When this rule runs
- When loading open purchase tables.

#### Full implementation flow
```text
Load open purchases
→ AccountingService.get_vendor_open_purchases()
→ vendor_rules.get_vendor_open_purchases()
→ Queries purchases with remaining due > 1e-9
→ Returns list of open purchase records
```

#### Inputs used
- `vendor_id`

#### Outputs produced
Tuple of dictionaries representing open purchases.

#### Calculation details
Filters purchases where `calculated_total - paid_amount - advance_applied > 1e-9`.

#### Constraints and validations
None.

#### Data read
- Tables: `purchases`, `purchase_detailed_totals`

#### Data written or side effects
None.

#### Edge cases handled
- Excludes fully paid purchases.

#### Edge cases not clearly handled
None.

#### Example scenario
- Returns purchases #1 and #2 if they have unpaid balances, but excludes purchase #3 if it is fully paid.

#### Implementation references
- Implementation: `modules/accounting/current_rules/vendor_rules.py` — `get_vendor_open_purchases`

#### Original call-site references
- `modules/vendor/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_open_purchases.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### VND-RULE-006: Supplier Refunds

#### Plain-English explanation
This rule records a cash refund received from a supplier, which matches against return values and decreases our outstanding receivable from them.

#### Why this rule exists in the application
To track cash returned by vendors for product returns rather than keeping store credit.

#### When this rule runs
- When logging a cash refund from a vendor.

#### Full implementation flow
```text
Record refund
→ AccountingService.record_supplier_refund_event()
→ vendor_rules.record_supplier_refund_event()
→ Validates refund details
→ Inserts row into purchase_refunds
→ Updates purchase totals
```

#### Inputs used
- `payload: SupplierRefundPayload`

#### Outputs produced
Refund ID.

#### Calculation details
Reduces outstanding return credit by the cash amount refunded.

#### Constraints and validations
- Refund amount must be positive.

#### Data read
- Tables: `purchases`, `purchase_refunds`

#### Data written or side effects
- Writes to `purchase_refunds`
- Recalculates purchase payment status

#### Edge cases handled
- Validates active bank accounts.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Supplier refunds $150 cash for returned items.
Records $150 row in purchase_refunds, marked as cleared.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/vendor_rules.py` — `record_supplier_refund_event`

#### Original call-site references
- `modules/vendor/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_supplier_refund.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

## 7. Sales Accounting Rules (SAL)

### SAL-RULE-001: Sale Financial Summary

#### Plain-English explanation
This rule calculates financial totals for a sale order: the net invoice amount, the amount paid by the customer, customer credit applied, any returned items, and the remaining outstanding balance.

#### Why this rule exists in the application
To track accounts receivable (AR) and outstanding invoice balances.

#### When this rule runs
- When loading a sale order invoice or detail view.

#### Full implementation flow
```text
Load sale view
→ AccountingService.get_sale_financial_summary()
→ sales_rules.get_sale_financial_summary()
→ Fetches sale receivable totals
→ Computes outstanding balance
→ Returns SaleFinancialSummary DTO
```

#### Inputs used
- `sale_id`

#### Outputs produced
`SaleFinancialSummary` DTO.

#### Calculation details
- `outstanding` = `net_total` - `paid_amount` - `applied_credit`.

#### Constraints and validations
- Sale must exist.

#### Data read
- Views: `sale_receivable_totals`

#### Data written or side effects
None.

#### Edge cases handled
- Handles sales with no payments or returns.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Sale total = $500.
Paid = $300. Applied credit = $50.
Outstanding = $150.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `get_sale_financial_summary`

#### Original call-site references
- `modules/sales/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_sale_outstanding.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### SAL-RULE-002: Sale Totals Calculation

#### Plain-English explanation
This rule calculates gross subtotals, item-level discounts, order-level discounts, returned item values, and net totals for a sale.

#### Why this rule exists in the application
To establish the base invoice totals for customer billing.

#### When this rule runs
- When creating or editing a sale.

#### Full implementation flow
```text
Calculate sale totals
→ AccountingService.get_sale_totals()
→ sales_rules.get_sale_totals()
→ Queries sale detailed totals and returned valuations
→ Computes net values
→ Returns SaleTotals DTO
```

#### Inputs used
- `sale_id`

#### Outputs produced
`SaleTotals` DTO.

#### Calculation details
- `net_total` = `subtotal` - `order_discount`.

#### Constraints and validations
- Sale must exist.

#### Data read
- Views: `sale_detailed_totals`
- Tables: `sales`

#### Data written or side effects
None.

#### Edge cases handled
- Subtracts returned valuations correctly.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Subtotal = $1,200.
Discount = $100.
Net total = $1,100.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `get_sale_totals`

#### Original call-site references
- `modules/sales/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_sale_totals.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### SAL-RULE-003: Sale Invoice Financials Context

#### Plain-English explanation
This rule aggregates customer information, product lines, discounts, payments, and return credits to assemble print layouts for sales invoices.

#### Why this rule exists in the application
To output PDF layouts and invoice previews.

#### When this rule runs
- When viewing or printing sales invoices.

#### Full implementation flow
```text
Print sale invoice
→ AccountingService.get_sale_invoice_financials()
→ sales_rules.get_sale_invoice_financials()
→ Fetches customer details, line items, and payment lists
→ Returns structured invoice context
```

#### Inputs used
- `sale_id`

#### Outputs produced
`SaleInvoiceFinancials` DTO.

#### Calculation details
Detailed breakdown of line discounts and tax factors.

#### Constraints and validations
- Sale must exist.

#### Data read
- Tables: `sales`, `sale_items`, `customers`, `sale_payments`

#### Data written or side effects
None.

#### Edge cases handled
- Handles cases where fields like billing address are missing.

#### Edge cases not clearly handled
None.

#### Example scenario
- Returns print context containing customer name, item table, paid history, and net amount due.

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `get_sale_invoice_financials`

#### Original call-site references
- `modules/sales/invoice_preview.py`

#### Test references
- `tests/accounting/test_customer_sales_invoice_financials.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### SAL-RULE-004: Sale Return Event Processing

#### Plain-English explanation
This rule registers customer product returns. It determines if a refund is allowed, caps the refund based on payments already cleared, validates the refund details (supporting Cash, Bank Transfer, Cheque, etc., with associated bank/instrument metadata), records the refund in sale payments, and converts any remaining value to customer store credit (return credit).

#### Why this rule exists in the application
To return products, adjust stock counts, reverse sales totals, and manage refunds (cash or bank/cheque) and store credits.

#### When this rule runs
- When submitting a customer return.

#### Full implementation flow
```text
Log return
→ AccountingService.record_sale_return_event()
→ sales_rules.record_sale_return_event()
→ Validates return boundaries
→ Validates refund method and bank details if non-cash
→ Inserts refund row (negative) into sale_payments
→ Inserts credit advances if any credit remainder
→ Returns SaleReturnEffect DTO
```

#### Inputs used
- `payload: SaleReturnPayload`

#### Outputs produced
`SaleReturnEffect` DTO.

#### Calculation details
- `settlement_due` = `return_value` - `outstanding_due_before`.
- `cash_refund` = Min of requested refund, cleared paid amount, and remaining settlement due.
- `credit_amount` = `settlement_due` - `cash_refund`.

#### Constraints and validations
- Return quantities cannot exceed original purchase quantities.
- Refund amount cannot exceed cleared customer payments.
- If refund is non-cash (e.g. Bank Transfer, Cheque), validates company bank account is active and instrument numbers are present.

#### Data read
- Tables: `sales`, `sale_payments`, `customer_advances`, `company_bank_accounts`

#### Data written or side effects
- Writes to `sale_payments` (negative amount for refunds, with the specified method and bank details)
- Writes to `customer_advances` (on credit note settlement)
- Writes to `inventory_transactions`
- Updates `sales.payment_status`

#### Edge cases handled
- Caps refund amount to prevent returning cash/bank funds that were never cleared.

#### Edge cases not clearly handled
- Returns allocated order discount as `Decimal("0")` in python code while database triggers aggregate values.

#### Example scenario
```text
Sale total = $500, paid = $500.
Return value = $200.
Outstanding = $0. Settlement due = $200.
Refund cash = $200 (if requested and paid before).
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `record_sale_return_event`

#### Original call-site references
- `modules/sales/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_sale_return_financials.py`

#### Confidence
High.

#### Possible later correctness review
- Ensure python payload matches database valuations regarding allocated discounts.

---

### SAL-RULE-005: Customer Payment Recording & Overpayment Conversion

#### Plain-English explanation
This rule records customer payments. If the cleared payment exceeds the outstanding amount on the invoice, the excess is automatically converted into customer store credit.

#### Why this rule exists in the application
To record receipts and handle overpayments by converting them to credit.

#### When this rule runs
- When logging a customer receipt.

#### Full implementation flow
```text
Submit receipt
→ AccountingService.record_customer_payment_event()
→ sales_rules.record_customer_payment_event()
→ Inserts row into sale_payments
→ If state is cleared, checks for overpayment
→ Inserts excess to customer_advances
→ Returns CustomerPaymentResult DTO
```

#### Inputs used
- `payload: CustomerPaymentPayload`

#### Outputs produced
`CustomerPaymentResult` DTO.

#### Calculation details
- `excess` = `cleared_amount` - `outstanding_amount`.
- If `excess > 0`, writes `excess` to `customer_advances`.

#### Constraints and validations
- Payment amount must be positive.

#### Data read
- Tables: `sales`, `sale_payments`

#### Data written or side effects
- Writes to `sale_payments`
- Writes to `customer_advances` (on overpayment)
- Updates `sales.payment_status`

#### Edge cases handled
- Converts excess payments into advances automatically.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Outstanding due = $150.
Customer pays = $200.
Payment clears. Invoice outstanding drops to $0.
Excess of $50 is written to customer_advances.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `record_customer_payment_event`

#### Original call-site references
- `modules/sales/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_payment_event.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### SAL-RULE-006: Customer Payment Status Transition & Reversal

#### Plain-English explanation
This rule handles transitions for customer receipts (e.g. pending/posted -> cleared/bounced). Clearing a payment applies excess allocations, while bouncing/reopening reverses the transaction, adjusting customer credit and outstanding invoice balances.

#### Why this rule exists in the application
To manage check clearances, handle bounced payments, and reverse incorrect entries.

#### When this rule runs
- When changing clearing state in the UI.
- When reversing/reopening a transaction.

#### Full implementation flow
```text
Reopen/bounce payment
→ AccountingService.reopen_customer_payment_state()
→ sales_rules.reopen_customer_payment_state()
→ Checks if excess credit was consumed
→ Inserts negative adjustment in customer_advances
→ Resets payment state to pending
```

#### Inputs used
- `payment_id`, `reason`

#### Outputs produced
Transition status (1 = success).

#### Calculation details
Subtracts previously granted advances if a payment bounces or is reopened.

#### Constraints and validations
- Bouncing/reopening requires a written reason.
- Reopening fails if the excess credit note was already spent.

#### Data read
- Tables: `sale_payments`, `customer_advances`

#### Data written or side effects
- Writes to `customer_advances` (reversal entries)
- Updates `sale_payments.clearing_state`
- Updates `sales.payment_status`

#### Edge cases handled
- Blocks reversals if the customer has already spent the overpayment credit.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Cleared payment of $200 bounced (was overpaid by $50).
Checks customer credit balance.
If balance >= $50, inserts -$50 to customer_advances.
Updates clearing state to pending.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `reopen_customer_payment_state`

#### Original call-site references
- `modules/sales/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_payment_status.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### SAL-RULE-007: Quotation Conversion

#### Plain-English explanation
This rule checks if a quotation exists and is in draft/sent state, then converts it into a sale order.

#### Why this rule exists in the application
To convert sales pitches and quotes into invoices without manual entry.

#### When this rule runs
- When converting a quotation to a sale.

#### Full implementation flow
```text
Convert quote to sale
→ AccountingService.record_quotation_conversion_event()
→ sales_rules.record_quotation_conversion_event()
→ Validates quotation conversion
→ Creates sale order and copies items
→ Marks quotation as converted
```

#### Inputs used
- `quotation_id`

#### Outputs produced
Conversion result DTO.

#### Calculation details
Copies prices and line totals from quotation.

#### Constraints and validations
- Quotation must be in draft/sent state.

#### Data read
- Tables: `quotations`, `quotation_items`

#### Data written or side effects
- Writes to `sales` and `sale_items`
- Updates `quotations.status`

#### Edge cases handled
- Rejects conversion if quotation was already converted.

#### Edge cases not clearly handled
None.

#### Example scenario
- Draft Quote #5 is converted to Sale #12.

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `record_quotation_conversion_event`

#### Original call-site references
- `modules/sales/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_quotation_behavior.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### SAL-RULE-008: Sale COGS Aggregation

#### Plain-English explanation
This rule calculates the Cost of Goods Sold (COGS) for products shipped in a sale, based on their purchase cost.

#### Why this rule exists in the application
To compute gross margins and profits for sales and reporting.

#### When this rule runs
- When running sales profit reports.

#### Full implementation flow
```text
Run profit report
→ AccountingService.get_sale_cogs()
→ sales_rules.get_sale_cogs()
→ Aggregates product inventory transaction unit costs
→ Returns SaleCogsSummary DTO
```

#### Inputs used
- `sale_id`

#### Outputs produced
`SaleCogsSummary` DTO containing `cogs_total`.

#### Calculation details
Sums unit purchase costs for sold quantities.

#### Constraints and validations
None.

#### Data read
- Tables: `inventory_transactions`, `inventory_valuations`

#### Data written or side effects
None.

#### Edge cases handled
- Handles returns by netting out cost of returned items.

#### Edge cases not clearly handled
None.

#### Example scenario
- Sale #1 contains 2 units of Item A. Cost of Item A = $10/unit. COGS = $20.

#### Implementation references
- Implementation: `modules/accounting/current_rules/sales_rules.py` — `get_sale_cogs`

#### Original call-site references
- `modules/sales/reports.py`

#### Test references
None.

#### Confidence
High.

#### Possible later correctness review
None.

---

## 8. Customer Rules Explained

### CUST-RULE-001: Customer Advances & Credit Event

#### Plain-English explanation
This rule records an advance deposit or return credit on a customer's profile, validating that the company bank account selected is active.

#### Why this rule exists in the application
To keep track of deposits and credits that customers have with us.

#### When this rule runs
- When logging a customer credit or prepayment.

#### Full implementation flow
```text
Record credit
→ AccountingService.record_customer_credit_event()
→ customer_rules.record_customer_credit_event()
→ Validates company bank account is active
→ Inserts row into customer_advances
```

#### Inputs used
- `payload: CustomerCreditPayload`

#### Outputs produced
Credit ID.

#### Calculation details
Increases customer credit balance.

#### Constraints and validations
- Bank account must be active.

#### Data read
- Tables: `company_bank_accounts`

#### Data written or side effects
- Writes to `customer_advances`

#### Edge cases handled
- Validates bank account status.

#### Edge cases not clearly handled
None.

#### Example scenario
- Customer deposits $1,000. Records a $1,000 deposit row in `customer_advances`.

#### Implementation references
- Implementation: `modules/accounting/current_rules/customer_rules.py` — `record_customer_credit_event`

#### Original call-site references
- `modules/customer/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_customer_credit_event.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### CUST-RULE-002: Customer Credit Application

#### Plain-English explanation
This rule allocates a customer's available store credit or deposit balance to pay off an outstanding sale invoice.

#### Why this rule exists in the application
To let customers pay invoices using their available credit balances.

#### When this rule runs
- When applying store credit to an unpaid invoice.

#### Full implementation flow
```text
Apply store credit
→ AccountingService.record_customer_credit_application_event()
→ customer_rules.record_customer_credit_application_event()
→ Checks customer credit balance
→ Inserts allocation row
→ Updates sale paid amount
```

#### Inputs used
- `payload: CustomerCreditApplicationPayload`

#### Outputs produced
Result DTO.

#### Calculation details
Allocates credit amount to the sale.

#### Constraints and validations
- Customer must have enough available credit.
- Sale outstanding must be greater than zero.

#### Data read
- Tables: `sales`, `customer_advances`

#### Data written or side effects
- Writes to `customer_advances` (negative row to draw down balance)
- Updates `sales.paid_amount`

#### Edge cases handled
- Rejects application if the customer's available credit balance is insufficient.

#### Edge cases not clearly handled
None.

#### Example scenario
- Customer applies $100 of credit to Sale #1. Writes -$100 to `customer_advances` and updates Sale #1 paid amount.

#### Implementation references
- Implementation: `modules/accounting/current_rules/customer_rules.py` — `record_customer_credit_application_event`

#### Original call-site references
- `modules/customer/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_credit_application.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### CUST-RULE-003: Customer History Timeline

#### Plain-English explanation
This rule builds a chronological timeline of all activities for a customer: sales orders, payments received, returns, and credits applied.

#### Why this rule exists in the application
To display a comprehensive transaction history on customer detail screens.

#### When this rule runs
- When opening a customer profile page.

#### Full implementation flow
```text
Open customer profile
→ AccountingService.get_customer_history()
→ customer_rules.get_customer_history()
→ Fetches sales, payments, returns, and advances
→ Sorts chronologically
→ Returns dictionary structure
```

#### Inputs used
- `customer_id`

#### Outputs produced
Timeline dictionary.

#### Calculation details
Combines multiple transaction tables.

#### Constraints and validations
None.

#### Data read
- Tables: `sales`, `sale_payments`, `customer_advances`

#### Data written or side effects
None.

#### Edge cases handled
- Formats empty timelines gracefully.

#### Edge cases not clearly handled
None.

#### Example scenario
- Lists Sale on Jan 1, Payment on Jan 2, Return on Jan 5.

#### Implementation references
- Implementation: `modules/accounting/current_rules/customer_rules.py` — `get_customer_history`

#### Original call-site references
- `modules/customer/controller.py`

#### Test references
- `tests/accounting/test_customer_sales_customer_statement.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### CUST-RULE-004: Customer Statement

#### Plain-English explanation
This rule retrieves customer advances, deposits, and credit applications to compile a running statement balance.

#### Why this rule exists in the application
To generate statements of store credit and pre-payment activity for customers.

#### When this rule runs
- When generating customer statement PDFs.

#### Full implementation flow
```text
Generate customer statement
→ AccountingService.get_customer_statement()
→ customer_rules.get_customer_statement()
→ Queries customer_advances table
→ Computes running balance of pre-payments
→ Returns CustomerStatement DTO
```

#### Inputs used
- `customer_id`

#### Outputs produced
`CustomerStatement` DTO.

#### Calculation details
- `running_balance` = `running_balance` + `tx_amount`.

#### Constraints and validations
None.

#### Data read
- Tables: `customer_advances`

#### Data written or side effects
None.

#### Edge cases handled
- Handles cases where no advance records exist.

#### Edge cases not clearly handled
- Unlike the vendor statement (which includes invoices and payments), the customer statement only lists records from `customer_advances`. Cash sales and invoice lines are excluded.

#### Example scenario
- Displays: Deposit of $500, Application of $200. Closing store credit balance = $300.

#### Implementation references
- Implementation: `modules/accounting/current_rules/customer_rules.py` — `get_customer_statement`

#### Original call-site references
- `modules/customer/reports.py`

#### Test references
- `tests/accounting/test_customer_sales_customer_statement.py`

#### Confidence
High.

#### Possible later correctness review
- Reconcile the discrepancy between customer statement (advances only) and vendor statement (purchases, payments, and advances) to achieve functional symmetry.

---

### CUST-RULE-005: Customer Aging Report

#### Plain-English explanation
This rule calculates how much money is owed to us by customers, categorized by age brackets (e.g. 0-30 days, 31-60 days, 61-90 days, 91+ days).

#### Why this rule exists in the application
To trace overdue accounts receivable (AR) and determine collection priorities.

#### When this rule runs
- When loading AR aging reports.

#### Full implementation flow
```text
Load aging report
→ AccountingService.get_customer_aging()
→ customer_rules.get_customer_aging()
→ Queries unpaid sales
→ Groups outstanding amounts by age based on sales date
→ Returns aging rows
```

#### Inputs used
- `customer_id`

#### Outputs produced
Aging rows grouped by age brackets.

#### Calculation details
Categorizes outstanding amount into brackets based on the difference between the sale date and the current date.

#### Constraints and validations
None.

#### Data read
- Tables: `sales`, `sale_payments`

#### Data written or side effects
None.

#### Edge cases handled
- Excludes fully paid sales.

#### Edge cases not clearly handled
None.

#### Example scenario
- Sale outstanding = $200 (date is 45 days ago) is grouped in the 31-60 days aging bracket.

#### Implementation references
- Implementation: `modules/accounting/current_rules/customer_rules.py` — `get_customer_aging`

#### Original call-site references
- `modules/customer/reports.py`

#### Test references
- `tests/accounting/test_customer_sales_reports.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### CUST-RULE-006: Customer Receivable Summary

#### Plain-English explanation
This rule calculates summary metrics for a customer: open invoice counts, credit balances, total unpaid amounts, and first/last transaction dates.

#### Why this rule exists in the application
To display high-level receivables summaries on customer dashboard lists.

#### When this rule runs
- When loading customer dashboard cards.

#### Full implementation flow
```text
Load dashboard cards
→ AccountingService.get_customer_receivable_summary()
→ customer_rules.get_customer_receivable_summary()
→ Queries customer sales totals and credit balances
→ Returns CustomerReceivableSummary DTO
```

#### Inputs used
- `customer_id`

#### Outputs produced
`CustomerReceivableSummary` DTO.

#### Calculation details
Aggregates open count, open due sum, and credit balance.

#### Constraints and validations
None.

#### Data read
- Tables: `sales`, `customer_advances`

#### Data written or side effects
None.

#### Edge cases handled
- Returns zero metrics if customer has no transactions.

#### Edge cases not clearly handled
None.

#### Example scenario
- Displays: Customer has 2 open invoices, total due of $450, and store credit balance of $50.

#### Implementation references
- Implementation: `modules/accounting/current_rules/customer_rules.py` — `get_customer_receivable_summary`

#### Original call-site references
- `modules/customer/controller.py`

#### Test references
None.

#### Confidence
High.

#### Possible later correctness review
None.

---

## 9. Expense Rules Explained

### EXP-RULE-001: Expense Lifecycle write events

#### Plain-English explanation
This rule manages expense entries (create, update, delete), verifying description lengths, positive amounts, and active categories.

#### Why this rule exists in the application
To track business overhead costs and other expenses.

#### When this rule runs
- When logging, modifying, or deleting an expense entry.

#### Full implementation flow
```text
Log expense
→ AccountingService.record_expense_create_event()
→ expense_rules.record_expense_create_event()
→ Validates amount, date, and category ID
→ Inserts row into expenses table
```

#### Inputs used
- `description`, `amount`, `date`, `category_id`

#### Outputs produced
Expense ID (for creation) or None.

#### Calculation details
Applies validation gates before mutating data.

#### Constraints and validations
- Description must not be empty.
- Amount must be positive.
- Category must exist (if category ID is provided).

#### Data read
- Tables: `expense_categories`

#### Data written or side effects
- Writes to `expenses`

#### Edge cases handled
- Rejects negative or zero amounts.

#### Edge cases not clearly handled
- Does not check if the expense date is in the future.

#### Example scenario
```text
Log rent expense of $800.
Inserts $800 row into expenses.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/expense_rules.py` — `record_expense_create_event`

#### Original call-site references
- `modules/expense/controller.py`

#### Test references
- `tests/accounting/test_expense_write_events.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### EXP-RULE-002: Expense Category write events

#### Plain-English explanation
This rule manages expense categories (create, update, delete). If an expense category is referenced by existing transactions, deleting it is blocked.

#### Why this rule exists in the application
To group expenses for reporting and prevent broken links when categories are deleted.

#### When this rule runs
- When adding, editing, or deleting an expense category.

#### Full implementation flow
```text
Delete category
→ AccountingService.record_expense_category_delete_event()
→ expense_rules.record_expense_category_delete_event()
→ Checks if expenses reference the category
→ Deletes category from expense_categories
```

#### Inputs used
- `category_id`, `name`

#### Outputs produced
None.

#### Calculation details
Validation checks.

#### Constraints and validations
- Name must not be empty.
- Cannot delete category if linked expenses exist.

#### Data read
- Tables: `expenses`, `expense_categories`

#### Data written or side effects
- Writes to `expense_categories`

#### Edge cases handled
- Blocks deletion of categories that have linked expenses.

#### Edge cases not clearly handled
None.

#### Example scenario
- Attempting to delete "Utilities" category fails if there are utilities expenses logged.

#### Implementation references
- Implementation: `modules/accounting/current_rules/expense_rules.py` — `record_expense_category_delete_event`

#### Original call-site references
- `modules/expense/controller.py`

#### Test references
- `tests/accounting/test_expense_category_lifecycle.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### EXP-RULE-003: Expense Dashboard & Profit-Loss summaries

#### Plain-English explanation
This rule calculates expense totals over a date range for dashboard views and profit & loss summaries.

#### Why this rule exists in the application
To display total overhead costs and calculate net profit margins.

#### When this rule runs
- When loading dashboard screens or generating financial profit reports.

#### Full implementation flow
```text
Load dashboard
→ AccountingService.get_dashboard_expense_total()
→ expense_rules.get_dashboard_expense_total()
→ Queries expense sums within date ranges
→ Returns total expense amount (Decimal)
```

#### Inputs used
- `date_from`, `date_to`

#### Outputs produced
Expense total (Decimal) and `ExpenseProfitLossSummary`.

#### Calculation details
Sums up all expense amounts within the date range.

#### Constraints and validations
None.

#### Data read
- Tables: `expenses`

#### Data written or side effects
None.

#### Edge cases handled
- Returns `Decimal("0")` if no expenses match the date range.

#### Edge cases not clearly handled
None.

#### Example scenario
```text
Expenses: Jan 1 = $200, Jan 15 = $100.
Dashboard total for January = $300.
```

#### Implementation references
- Implementation: `modules/accounting/current_rules/expense_rules.py` — `get_dashboard_expense_total`

#### Original call-site references
- `modules/expense/reports.py`

#### Test references
- `tests/accounting/test_expense_dashboard_totals.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### EXP-RULE-004: Expense Reporting & Row reads

#### Plain-English explanation
This rule retrieves filtered rows and group totals for expense reports based on query strings, dates, categories, and amounts.

#### Why this rule exists in the application
To generate detailed expense reports and exports.

#### When this rule runs
- When applying filters on expense list screens or running reporting tools.

#### Full implementation flow
```text
Apply filter
→ AccountingService.list_expense_rows()
→ expense_rules.list_expense_rows()
→ Dynamically builds SQL WHERE clauses
→ Queries expenses and category tables
→ Returns list of expense records
```

#### Inputs used
- `query`, `date`, `date_from`, `date_to`, `category_id`, `amount_min`, `amount_max`

#### Outputs produced
Tuple of `ExpenseFinancialSummary` DTOs.

#### Calculation details
Applies SQL filters for bounds.

#### Constraints and validations
None.

#### Data read
- Tables: `expenses`, `expense_categories`

#### Data written or side effects
None.

#### Edge cases handled
- Handles cases where no filters are specified.

#### Edge cases not clearly handled
None.

#### Example scenario
- Returns all utility expenses between $100 and $500 logged in March.

#### Implementation references
- Implementation: `modules/accounting/current_rules/expense_rules.py` — `list_expense_rows`

#### Original call-site references
- `modules/expense/reports.py`

#### Test references
- `tests/accounting/test_expense_report_reads.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

## 10. Bank and Cash Rules Explained

### BANK-RULE-001: Bank Ledger Aggregation

#### Plain-English explanation
This rule compiles all transactions affecting the company's bank accounts, pulling from cash sales, purchase payments, and vendor advances to show a running ledger history.

#### Why this rule exists in the application
To reconcile company bank balances.

#### When this rule runs
- When viewing the bank ledger screen.

#### Full implementation flow
```text
Open bank ledger
→ AccountingService.get_bank_ledger()
→ bank_rules.get_bank_ledger()
→ Queries v_bank_ledger_ext view
→ Merges vendor advance records
→ Returns chronological ledger list
```

#### Inputs used
- `start_date`, `end_date`, `account_id`

#### Outputs produced
Tuple of `BankLedgerRow` DTOs.

#### Calculation details
Sorts transactions chronologically to calculate running balances.

#### Constraints and validations
None.

#### Data read
- Views: `v_bank_ledger_ext`
- Tables: `vendor_advances`

#### Data written or side effects
None.

#### Edge cases handled
- Excludes transactions that have not cleared yet.

#### Edge cases not clearly handled
None.

#### Example scenario
- Lists: Receipt from Customer A on Jan 1 (+$200), Direct payment to Vendor B on Jan 2 (-$150).

#### Implementation references
- Implementation: `modules/accounting/current_rules/bank_rules.py` — `get_bank_ledger`

#### Original call-site references
- `modules/bank/reports.py`

#### Test references
None.

#### Confidence
High.

#### Possible later correctness review
None.

---

### BANK-RULE-002: Vendor/Customer Cash Movements

#### Plain-English explanation
This rule gathers all incoming and outgoing cash flows (payments, advances, refunds) for a customer or vendor.

#### Why this rule exists in the application
To show cash movement summaries on vendor and customer dashboards.

#### When this rule runs
- When loading cash flow cards on vendor or customer profile pages.

#### Full implementation flow
```text
Open cash flow card
→ AccountingService.get_vendor_cash_movements()
→ bank_rules.get_vendor_cash_movements()
→ Queries direct payments, advances, and refunds
→ Returns list of cash movement entries
```

#### Inputs used
- `start_date`, `end_date`

#### Outputs produced
Tuple of `VendorCashMovement` or `CustomerCashMovement` DTOs.

#### Calculation details
Sums up transactions affecting cash/bank accounts.

#### Constraints and validations
None.

#### Data read
- Tables: `purchase_payments`, `vendor_advances`, `purchase_refunds`, `sale_payments`, `customer_advances`

#### Data written or side effects
None.

#### Edge cases handled
- Handles cases where no cash movements exist.

#### Edge cases not clearly handled
None.

#### Example scenario
- Returns cash outflows (total check payments and refunds) to Vendor X during February.

#### Implementation references
- Implementation: `modules/accounting/current_rules/bank_rules.py` — `get_vendor_cash_movements`

#### Original call-site references
- `modules/vendor/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_cash_movements.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

### BANK-RULE-003: Company & Vendor Bank Account Validations

#### Plain-English explanation
This rule validates that bank accounts referenced in payments are active, belong to the correct vendor/company, and are configured correctly.

#### Why this rule exists in the application
To prevent recording transactions against closed or wrong bank accounts.

#### When this rule runs
- When logging a payment or return refund.

#### Full implementation flow
```text
Validate bank account
→ bank_rules.validate_company_bank_account_active()
→ Checks active status flag on company_bank_accounts table
→ Raises ValueError if inactive or missing
```

#### Inputs used
- `bank_account_id`

#### Outputs produced
None (raises ValueError on failure).

#### Calculation details
Validation checks.

#### Constraints and validations
- Bank account must exist and have status 'active'.
- Vendor bank account must belong to the specified vendor.

#### Data read
- Tables: `company_bank_accounts`, `vendor_bank_accounts`

#### Data written or side effects
None.

#### Edge cases handled
- Raises clean errors with descriptive messages (e.g. "Bank account is inactive") to block bad entries.

#### Edge cases not clearly handled
None.

#### Example scenario
- Attempting to log a payment using a bank account that is marked inactive raises a ValueError, blocking the transaction.

#### Implementation references
- Implementation: `modules/accounting/current_rules/bank_rules.py` — `validate_company_bank_account_active`

#### Original call-site references
- `modules/accounting/validators.py`

#### Test references
- `tests/accounting/test_vendor_purchase_payment_metadata_validation.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

## 11. Inventory / Cost / Margin / COGS Rules Explained

### INV-RULE-001: Purchase/Sale Inventory Event

#### Plain-English explanation
This rule records product inventory transactions (purchases, sales, purchase returns, sales returns) in the stock ledger and triggers a recalculation of FIFO/weighted costing valuations for stock on hand.

#### Why this rule exists in the application
To track physical inventory stock levels and calculate accurate product unit costs.

#### When this rule runs
- When saving a purchase order, sale order, purchase return, or sale return.

#### Full implementation flow
```text
Save transaction
→ AccountingService.record_purchase_inventory_event()
→ inventory_rules.record_purchase_inventory_event()
→ Inserts rows into inventory_transactions
→ Triggers inventory costing recalculation
→ Returns result DTO with transaction IDs
```

#### Inputs used
- `payload: PurchaseInventoryPayload` (lines containing product ID, quantities, UOMs, and transaction dates)

#### Outputs produced
Result DTO.

#### Calculation details
Triggers the FIFO cost layer builder to recalculate cost valuations.

#### Constraints and validations
- Product and UOM must be valid.

#### Data read
- Tables: `purchase_items`, `sale_items`

#### Data written or side effects
- Writes to `inventory_transactions`
- Rebuilds `inventory_valuations`

#### Edge cases handled
- Recalculates cost layers chronologically to ensure valuation history remains correct.

#### Edge cases not clearly handled
None.

#### Example scenario
- Receiving 100 units of Product A creates a 'purchase' type entry in `inventory_transactions` and updates its costing layer.

#### Implementation references
- Implementation: `modules/accounting/current_rules/inventory_rules.py` — `record_purchase_inventory_event`

#### Original call-site references
- `modules/purchase/controller.py`

#### Test references
- `tests/accounting/test_vendor_purchase_inventory_effects.py`

#### Confidence
High.

#### Possible later correctness review
None.

---

## 12. Status Rules Explained

### purchase.payment_status / sales.payment_status
Payment status values are derived dynamically based on totals vs payments:
- **Paid**: `remaining_due <= 1e-9` (matches remaining outstanding close to zero).
- **Partial**: `paid_amount > 1e-9` or `applied_credit > 1e-9`, but `remaining_due > 1e-9` (meaning some payments or credits were applied, but outstanding balance remains).
- **Unpaid**: `paid_amount <= 1e-9` and `applied_credit <= 1e-9` and `remaining_due > 1e-9` (no payments or credits applied yet).

The status recalculation functions (`recalculate_purchase_payment_status` and `recalculate_sale_payment_status`) update these derived states in the database (`purchases.payment_status`, `sales.payment_status`).

---

## 13. Report / Display / Template Rules Explained
The reporting rules delegate calculations to `AccountingService`:
- **Invoice Layouts**: Query `get_purchase_invoice_financials` and `get_sale_invoice_financials` to populate customer printouts.
- **Profit & Loss**: Combines sales revenue, COGS (Cost of Goods Sold), and total category expenses from `get_profit_loss_expense_summary` to return net profit margins.
- **AR & AP Aging**: Groups open invoices by age brackets using `get_customer_aging` and `get_vendor_aging`.

---

## 14. Rule Dependency Map

### Purchase / Vendor Dependency Map
```text
Vendor balance (running Statement of Account)
← purchase outstanding (PUR-RULE-001)
← vendor payments (VND-RULE-002)
← vendor advances (VND-RULE-001)
← purchase returns (PUR-RULE-003)
← supplier refunds (VND-RULE-006)
```

### Sales / Customer Dependency Map
```text
Customer credit balance / advances
← customer payments / overpayment conversion (SAL-RULE-005)
← customer credit application (CUST-RULE-002)
← sale returns credit note (SAL-RULE-004)
← customer credit reversal on bounced payment (SAL-RULE-006)
```

### Expenses Dependency Map
```text
Expense Category Totals
← expense write events (EXP-RULE-001)
← expense category validation (EXP-RULE-002)
```

### Banking / Cash Dependency Map
```text
Bank Ledger running balances
← v_bank_ledger_ext (view)
← direct vendor payments (cleared only)
← direct customer receipts (cleared only)
← vendor advance deposits
← supplier cash refunds
```

### Inventory / Cost Dependency Map
```text
Product Cost Valuation (FIFO)
← inventory stock transactions (INV-RULE-001)
← purchase return stock validation (PUR-RULE-003)
```

---

## 15. Constraints Summary

| Constraint | Area | Enforced Where | Applies To | Tests | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Return qty <= purchased qty | PUR | `purchase_rules.py` | Purchase Returns | `test_vendor_purchase_return_event.py` | Blocks returning more than purchased |
| Return qty <= stock on hand | PUR | `purchase_rules.py` | Purchase Returns | `test_vendor_purchase_return_event.py` | Blocks returning items not in inventory |
| Refund Now requires fully settled | PUR | `purchase_rules.py` | Refund Now | `test_vendor_purchase_return_event.py` | Rejects refund if purchase has remaining due |
| Active bank account required | BANK | `bank_rules.py` | Payments/Refunds | `test_vendor_purchase_payment_metadata_validation.py` | Rejects inactive bank accounts |
| Refund cap <= cleared payments | SAL | `sales_rules.py` | Sales Returns | `test_customer_sales_sale_return_financials.py` | Rejects refunds exceeding paid amounts |
| Reopen requires reason | SAL | `sales_rules.py` | Reopen Payments | `test_customer_sales_payment_status.py` | Rejection fails without reason |
| Block category deletion if used | EXP | `expense_rules.py` | Categories | `test_expense_category_lifecycle.py` | Rejects deletion if expenses exist |

---

## 16. Side Effects Summary

| Side Effect | Trigger | Area | Data Written | Implementation Reference | Tests | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Overpayment to advance | Cleared Payment | VND / SAL | `vendor_advances`/`customer_advances` | `sales_rules._handle_overpayment` | `test_customer_sales_payment_event.py` | Excess goes to credit |
| Adjust paid amount | Recalculate status | PUR / SAL | `purchases`/`sales` | `purchase_rules.recalculate_purchase_payment_status` | `test_vendor_purchase_outstanding.py` | Updates status column |
| Rebuild costing layers | Inventory event | INV | `inventory_valuations` | `inventory_rules._rebuild_dirty_valuations` | `test_vendor_purchase_inventory_effects.py` | Costing update |
| Log audit record | Purchase return | PUR | `audit_logs` | `purchase_rules.record_purchase_return_event` | `test_vendor_purchase_return_event.py` | Logs action details |

---

## 17. Gaps and Unclear Areas

### 1. Customer Statement vs. Vendor Statement Discrepancy
- **What is unclear**: Why the customer statement is limited to `customer_advances` (deposits and pre-payments) whereas the vendor statement is a complete Statement of Account including purchases and cash payments.
- **Files involved**: `modules/accounting/current_rules/customer_rules.py` (L288-L331).
- **Later review**: Reconcile this discrepancy to ensure customer statements display all cash sales and invoices.

### 2. Hardcoded Return Values in python payloads
- **What is unclear**: Why the python payload returned by `sales_rules.record_sale_return_event` hardcodes `allocated_order_discount=Decimal("0")` and `cogs_reversal_value=Decimal("0")` when database triggers handle these calculations.
- **Files involved**: `modules/accounting/current_rules/sales_rules.py` (L481-L482).
- **Later review**: Verify whether the UI or reports expect correct values in these payload fields.

---

## 18. Possible Later Correctness Review Topics

### Purchase & Vendor
- Review whether partial return refunds should allow splitting between cash and store credit in a single operation.
- Investigate if direct column updates to `purchases.paid_amount` (outside of the payment ledger) should be prohibited.

### Sales & Customer
- Evaluate if customer statements should be expanded to include all invoices and cleared payments.
- Verify that quotation conversion preserves discounts and tax allocations.

### Expenses
- Confirm that deleting an expense category is blocked for all historical records.

### Bank & Cash
- Review the bank ledger query to ensure uncleared payments are excluded from balance totals.

---

## 19. Final Summary
- **Number of rules explained**: 34 rules mapped across PUR, VND, SAL, CUST, EXP, BANK, and INV subdomains.
- **Strongest explained areas**: Purchase, Sales, and Vendor payment lifecycles and overpayment conversion logic.
- **Weakest/unclear areas**: Customer statement fields (only lists pre-payments/deposits) and hardcoded python return values for returns.
- **Most important constraints found**: Stock availability validation for returns, inactive bank account rejection, and payment clearance caps.
- **Most important side effects found**: Automated overpayment-to-credit conversion and FIFO costing layer rebuilds.

**Verification Notes**:
- No code behavior was modified.
- No schema rules were corrected.
- This document explains currently implemented behavior only.
- No tests were run because this was a documentation-only task.
