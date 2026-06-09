# Complete Application Feature Document

This document consolidates the original feature list and the answered clarification batches into one clean business-focused requirements document. It uses your latest answers as the source of truth, especially where earlier answers were corrected or made clearer.   

---

# 1. Application overview

The application is a business management system for handling:

* Products and product units
* Inventory and stock valuation
* Vendors and vendor payments
* Purchases and purchase returns
* Customers and customer payments
* Sales, invoices, and sales returns
* Quotations
* Expenses
* Damaged inventory adjustment
* Reports
* Audit history

The application should help the user track stock, purchases, sales, payments, returns, advances, expenses, and profit/loss.

The main business focus is inventory and transaction control, not complex accounting.

---

# 2. User roles and access rules

## Current role model

For now, all users have the same access.

There is no separate admin, cashier, manager, or restricted user role at this stage.

## Access rules

All users can currently:

* Add and edit products where allowed
* Add vendors and customers
* Create purchases and sales
* Create drafts
* Edit purchases, sales, and payments where allowed
* Cancel sales
* Reactivate cancelled sales
* Record returns
* View margin if they choose to unhide it
* Approve or continue negative-margin sales after warning
* Edit or cancel payments
* View inventory and reports
* View audit history

## Important permission note

Because all users currently have the same access, permission control is not required in the first version.

Status: **Confirmed**

---

# 3. Global business rules

## 3.1 Quantity and decimal rules

* Decimal quantities are allowed for purchases and sales.
* Quantity values can have a maximum of 2 decimal places.
* Unit conversion factors can have a maximum of 2 decimal places.
* Calculated converted quantities should also be kept to 2 decimal places.
* Negative stock is not allowed.

Status: **Confirmed**

---

## 3.2 Draft rules

Drafts are allowed for purchases and sales.

Drafts must not affect real stock, payments, or invoices.

A draft purchase:

* Can be saved with no product selected.
* Can contain incomplete product lines.
* Does not increase inventory.
* Cannot receive payment.

A draft sale:

* Does not reserve stock.
* Cannot receive payment.
* Cannot generate an invoice.

Stock changes only after purchase confirmation or sale confirmation.

Status: **Confirmed**

---

## 3.3 Stock costing and valuation

The application uses FIFO for:

* Stock deduction during sales
* Margin calculation
* Inventory valuation
* Profit calculation
* Reports
* Damaged inventory cost calculation

Purchase returns are the exception and use LIFO.

Status: **Mostly clear**

Needs confirmation only if the developer needs an exact low-level rule for combining LIFO with user-selected PO lines.

---

## 3.4 Discounts

Discounts are entered as actual money amounts, not percentages.

Discounts can be applied:

* On a single product line
* On the whole order

Purchase discounts affect profit.

Needs confirmation:

* The exact allocation method for purchase discounts into FIFO cost layers is still not fully defined.

Status: **Needs confirmation**

---

## 3.5 Advances

Both vendors and customers can have advance balances.

Advance balance means extra money that can be used later.

Examples:

* If the business overpays a vendor, the extra amount becomes vendor advance.
* If a customer overpays, the extra amount becomes customer advance.
* If a return creates extra paid amount, the user can choose whether to refund it or add it to advance.

Vendor credit should not be treated as a separate concept. Use **vendor advance** everywhere.

Status: **Confirmed**

---

## 3.6 Audit history

Audit history is required for important changes.

Audit history should keep previous versions or traces for:

* Payment edits
* Payment cancellations
* Old invoice versions
* Edited transactions where required
* Cancelled payments hidden from normal screens
* Reports affected by edited payments

Reports should show current data, but the audit trail must still show what changed.

Status: **Confirmed**

---

# 4. Complete feature list

1. Product management
2. Base and alternative unit management
3. Inventory
4. Vendor management
5. Vendor bank accounts
6. Vendor advances
7. Purchases / purchase orders
8. Purchase payments
9. Purchase returns
10. Customer management
11. Customer advances
12. Sales
13. Sales payments
14. Sales returns
15. Sale invoices
16. Quotations
17. Expenses
18. Damaged inventory adjustment
19. Reports
20. Audit history

---

# 5. Detailed feature requirements

---

# 5.1 Product management

## Purpose

Allow users to create products that can later be purchased, stocked, sold, returned, and reported.

## User role

All users.

## Main user flow

1. User opens product screen.
2. User enters product details.
3. User selects a base unit.
4. User optionally adds alternative units.
5. User saves the product.
6. Product becomes available for purchase.

## Business rules

* A product must be added before it can be purchased.
* A product must be purchased before it can be sold.
* Products cannot be created directly from the purchase screen.
* If a purchase references a missing product, the system should show: **“Product doesn’t exist.”**

## Required inputs

* Product name
* Base unit
* Optional alternative units
* Conversion factor for each alternative unit

## Validation rules

* Product must have a base unit.
* Alternative unit conversion factor is required if an alternative unit is added.
* Alternative unit names must be unique per product.
* Quantity and conversion values allow up to 2 decimal places.
* Base unit cannot be changed after purchases or sales exist.
* Alternative unit cannot be deactivated if transactions exist.
* Alternative unit conversion factor cannot be edited after transactions exist.

## Success behavior

Product is saved and becomes available for purchases.

## Failure or blocked behavior

* If required fields are missing, product cannot be saved.
* If conversion factor is missing for an alternative unit, product cannot be saved.
* If product has transactions, base unit and used alternative unit rules are locked.

## Edge cases

* Products with multiple alternative units are allowed.
* Decimal stock quantities are allowed.
* Unit conversion must not create negative or invalid stock.

Status: **Confirmed**

---

# 5.2 Base and alternative units

## Purpose

Support products bought in one unit and sold in another unit.

Example: wire may be bought in bundles but sold in bundles or yards.

## User role

All users.

## Main user flow

1. User creates or edits product.
2. User selects base unit.
3. User adds one or more alternative units.
4. User enters conversion factor for each alternative unit.
5. System uses conversion factor during sales, purchases, inventory, and returns.

## Business rules

* Base unit is the main stock unit.
* Alternative units are optional.
* One product can have multiple alternative units.
* Each alternative unit has its own conversion factor.
* Example: 1 bundle = 97 yards.
* If selling in alternative unit, system should convert it to base stock internally.
* A single sale line can use either base unit or alternative unit, not both.
* If both units are needed in one sale, the user must add separate sale lines.

## Required inputs

* Base unit
* Alternative unit name
* Conversion factor

## Validation rules

* Conversion factor is mandatory.
* Conversion factor max 2 decimals.
* Quantity max 2 decimals.
* Alternative unit names unique per product.
* Used units cannot be changed/deactivated after transactions.

## Success behavior

The product can be bought and sold using configured units.

## Failure or blocked behavior

* Missing conversion factor blocks save.
* Used unit cannot be removed, deactivated, or changed.

## Edge cases

* Selling in alternative unit must still check available stock.
* Conversion result should be kept to 2 decimals.

Status: **Confirmed**

---

# 5.3 Inventory

## Purpose

Show current stock, stock value, stock movements, and related payments.

## User role

All users.

## Main user flow

1. User opens inventory screen.
2. User sees current inventory.
3. User can view product-wise stock.
4. User can view stock by unit.
5. User can view stock value.
6. User can view stock movement history.
7. User can view related payment history in a separate tab.

## Business rules

* Inventory shows current stock only, not historical stock by date.
* Inventory should show both quantity and value.
* Inventory should support product-wise and unit-wise views.
* Inventory should have separate areas/tabs for:

  * Stock movements
  * Related payments
* Negative stock is not allowed.
* Returns should appear in inventory history.
* Cancelled sales should appear as stock reversal entries.
* Cancelled sale reversal entries are visible to all users.
* Damaged inventory adjustments should appear as stock reduction entries in inventory history.

## Required data

* Product
* Unit
* Quantity
* Stock value
* Transaction type
* Transaction reference
* Date
* Related payment reference, where applicable

## Validation rules

* Stock cannot go below zero.
* Sale confirmation is blocked if stock is insufficient.
* Damaged inventory adjustment is blocked if quantity is not available.
* Drafts do not affect inventory.

## Success behavior

Inventory reflects confirmed purchases, sales, returns, cancellations, and damaged inventory adjustments.

## Failure or blocked behavior

* Sale with insufficient stock becomes draft instead of confirmed sale.
* Damaged inventory cannot be recorded if stock is unavailable.
* Purchase return cannot exceed available stock rules.

## Edge cases

* Cancelled sales restock inventory through reversal entries.
* Sales returns restock inventory.
* Damaged inventory reduces inventory.

Status: **Confirmed**

---

# 5.4 Vendor management

## Purpose

Store vendor details for purchases, payments, returns, and reports.

## User role

All users.

## Main user flow

1. User creates vendor from vendor screen or purchase screen.
2. User enters required vendor details.
3. User may add vendor bank accounts.
4. Vendor is saved and available for future purchases.

## Business rules

* Vendors can be created directly from purchase screen.
* New vendors created during purchase are retained for future purchases.
* Vendor advance balance should be shown when vendor is selected on PO screen.
* Vendor outstanding balance should also be visible where relevant.

## Required inputs

* Company name
* Representative name
* Address
* Phone
* Email optional

## Validation rules

* Company name required.
* Representative name required.
* Address required.
* Phone required.
* Email optional.

## Success behavior

Vendor is saved and selectable in purchases and payments.

## Failure or blocked behavior

Vendor cannot be saved if required fields are missing.

## Edge cases

* Vendor created inside purchase flow should be permanently saved.
* Vendor advances should be visible before saving PO.

Status: **Confirmed**

---

# 5.5 Vendor bank accounts

## Purpose

Store reusable vendor bank accounts and allow temporary bank accounts for one-off transactions.

## User role

All users.

## Main user flow

1. User opens vendor profile.
2. User adds vendor bank account.
3. User enters bank name and account number.
4. During payment, user selects saved vendor account or enters temporary account details.

## Business rules

* The earlier term “primary account” should be treated as “saved vendor account.”
* There is no special default account.
* A vendor can have multiple saved bank accounts.
* Saved vendor account requires bank name and account number.
* Temporary bank account details are not added to vendor profile.
* Temporary bank account details are stored in PO/payment transaction history.
* Used bank accounts cannot be deleted or marked inactive.
* Unused bank accounts can be deleted.

## Required inputs

For saved vendor account:

* Bank name
* Account number

For temporary account during payment:

* Bank name
* Account number
* Instrument number
* Date

## Validation rules

* Saved vendor account requires bank name and account number.
* Temporary bank account requires bank name, account number, instrument number, and date.
* Used account cannot be deleted.

## Success behavior

Saved accounts become available for future vendor payments.

## Failure or blocked behavior

* Missing bank details block account save.
* Used bank account cannot be deleted or deactivated.

## Edge cases

* Temporary bank accounts appear in payment reports/history but not in vendor profile.
* Vendor payment should also record the business’s own bank account used for payment.

Status: **Confirmed**

---

# 5.6 Vendor advances

## Purpose

Track extra money paid to vendors and allow it to be adjusted against future purchase orders.

## User role

All users.

## Main user flow

1. User records vendor advance directly, or system creates advance from overpayment/return.
2. Vendor advance appears when vendor is selected on PO screen.
3. User chooses whether to apply advance to the PO or leave it as is.

## Business rules

* Vendor advance can be created manually.
* Vendor advance can be created from overpayment.
* Vendor advance can be created from purchase return extra amount.
* Vendor credit and vendor advance are the same thing.
* Use the term **vendor advance** everywhere.
* Vendor advance should not be applied automatically.
* User should be asked whether to apply vendor advance against future PO.

## Required inputs

* Vendor
* Amount
* Date
* Payment method, where applicable
* Instrument details if non-cash

## Validation rules

* Advance amount must be greater than zero.
* Advance cannot be applied more than available balance.
* Draft purchase cannot receive advance adjustment.

## Success behavior

Vendor advance balance is updated and visible on vendor/PO screens.

## Failure or blocked behavior

* Cannot apply more advance than available.
* Cannot apply advance to draft PO as payment.

## Edge cases

* If purchase return creates extra paid amount, user chooses refund or vendor advance.
* Vendor advance should appear in vendor reports.

Status: **Confirmed**

---

# 5.7 Purchases / purchase orders

## Purpose

Allow users to create purchase orders, confirm stock, record purchase prices, sale prices, discounts, and initial payments.

## User role

All users.

## Main user flow

1. User opens purchase screen.
2. User selects existing vendor or adds a new vendor.
3. User adds purchase lines.
4. User selects products that already exist.
5. User enters quantity, purchase price, and sale price.
6. User adds line discount or order discount, if needed.
7. User chooses draft or confirmed PO.
8. On confirmation, stock increases.
9. User may record no payment, partial payment, full payment, or overpayment.

## Business rules

* Product must already exist before purchase.
* New vendor can be created during purchase.
* Purchase can be saved as draft.
* Draft purchase can have missing/incomplete product lines.
* Draft purchase does not affect inventory.
* Draft purchase cannot receive payment.
* Stock increases only when PO is confirmed.
* Same product can appear multiple times in one purchase.
* If same product appears multiple times with different purchase prices, FIFO should treat them as separate cost layers.
* Taxes, shipping, loading, and other purchase costs are not included.
* Sale price lower than purchase cost is allowed but should show warning.
* Negative margin is allowed with warning.
* Purchase discount affects profit.
* Initial payment can be:

  * No payment
  * Partial payment
  * Full payment
  * Overpayment
* Overpayment becomes vendor advance.

## Required inputs

* Vendor
* Product
* Quantity
* Unit
* Purchase price
* Sale price
* Optional line discount
* Optional order discount
* Payment method if payment is made
* Instrument details for non-cash payment

## Validation rules

* Confirmed PO requires valid product lines.
* Product must already exist.
* Quantity must be greater than zero.
* Quantity max 2 decimals.
* Purchase price required.
* Sale price required.
* If sale price is below purchase cost, show warning but allow.
* Draft PO can be incomplete.
* Payment cannot be recorded on draft PO.

## Success behavior

* Confirmed PO increases stock.
* Vendor balance updates.
* Payment status updates.
* Overpayment creates vendor advance.
* Purchase appears in purchase and inventory records.

## Failure or blocked behavior

* Missing product blocks confirmed purchase.
* Draft can be saved, but not paid.
* Invalid quantity blocks confirmation.

## Edge cases

* Multiple lines for same product are allowed.
* Different purchase prices create separate FIFO cost layers.
* Purchase discount allocation to profit/valuation needs confirmation.

Status: **Mostly clear**

Needs confirmation:

* Exact method for applying purchase discounts into FIFO cost/profit calculations.

---

# 5.8 Purchase payments

## Purpose

Allow payment against unpaid or partially paid purchase orders.

## User role

All users.

## Main user flow

1. User selects vendor or PO.
2. User selects a specific unpaid or partially paid PO.
3. User enters payment amount.
4. User chooses payment method.
5. User enters required payment details.
6. Payment is saved.
7. PO payment status updates.

## Business rules

* One payment applies to one specific PO.
* A payment cannot cover multiple POs.
* Payment cannot be made against general vendor balance without selecting a PO.
* Partial payment is allowed.
* Payment methods:

  * Cash
  * Cheque
  * Bank transfer
* Vendor cheque payments are treated as paid immediately when issued.
* Vendor cheque bounce handling is not needed for now.
* Payment records can be edited or cancelled.
* Edited payment must keep old version in audit history.
* Cancelled payment should disappear from normal payment lists but remain visible in audit history.
* All payments related to a PO should be saved in PO history.

## Required inputs

For cash:

* PO
* Amount
* Date

For cheque/bank transfer to saved vendor account:

* PO
* Amount
* Saved vendor bank account
* Instrument number
* Date
* Business bank account used for payment

For cheque/bank transfer to temporary account:

* PO
* Amount
* Bank name
* Account number
* Instrument number
* Date
* Business bank account used for payment

## Validation rules

* PO must be selected.
* Draft PO cannot receive payment.
* Payment amount must be greater than zero.
* Required non-cash fields must be present.
* Payment cannot exceed payable amount unless extra becomes vendor advance.

## Success behavior

* Payment is recorded.
* PO balance updates.
* Vendor balance updates.
* Audit trail records later edits/cancellations.

## Failure or blocked behavior

* Payment blocked if no PO selected.
* Payment blocked if PO is draft.
* Non-cash payment blocked if instrument details are missing.

## Edge cases

* Edited payments update current reports, but audit history remains.
* Cancelled payments disappear from normal screens but remain in audit.

Status: **Confirmed**

---

# 5.9 Purchase returns

## Purpose

Allow the business to return purchased goods to vendors and adjust stock, PO totals, vendor balance, refund, or vendor advance.

## User role

All users.

## Main user flow

1. User opens purchase return screen.
2. User selects vendor and PO.
3. User selects original PO line.
4. User enters return quantity.
5. System checks whether quantity is available in stock.
6. System reduces inventory immediately.
7. System recalculates PO total and outstanding balance.
8. If extra paid amount exists, user chooses refund or vendor advance.

## Business rules

* Purchase returns can happen multiple times for the same purchase, if quantity is available.
* Partial purchase returns are allowed.
* User selects original PO line being returned.
* Return quantity is based on remaining available stock.
* Purchase return uses LIFO.
* Latest answer says user can select any PO line if the products are still in stock.
* Returned quantity reduces inventory immediately.
* Refunds from vendor can be received by:

  * Cash
  * Bank transfer
  * Cheque
* Refund by non-cash requires instrument number.
* If PO is unpaid, return updates PO total and outstanding amount.
* If PO is partially paid, paid amount is applied to remaining bill and unpaid amount is reduced accordingly.
* If return creates extra paid amount, user chooses:

  * Receive refund now
  * Add amount to vendor advance
* Vendor advance can be used against future POs when user chooses.
* Purchase return can be edited or cancelled.
* Editing/cancelling purchase return should reverse or update inventory and vendor balance accordingly.

## Required inputs

* Vendor
* PO
* PO line
* Product
* Quantity to return
* Unit
* Return date
* Refund/advance decision if money is involved
* Refund method and instrument details if refund selected

## Validation rules

* Return quantity must be greater than zero.
* Return quantity cannot exceed available stock.
* Return quantity max 2 decimals.
* Product must belong to selected PO.
* Draft PO cannot have purchase return.
* Refund method details required when refund is selected.

## Success behavior

* Inventory decreases.
* PO totals update.
* Vendor balance updates.
* Refund or vendor advance is recorded.

## Failure or blocked behavior

* Return blocked if quantity is unavailable.
* Return blocked if product/PO line is invalid.
* Refund blocked if required payment details are missing.

## Edge cases

* Multiple returns against same PO are allowed if stock remains.
* If return creates extra paid amount, user chooses refund or vendor advance.
* Purchase return LIFO + selected PO line behavior is mostly clear but may need exact developer interpretation.

Status: **Mostly clear**

Needs confirmation:

* Exact rule when LIFO order conflicts with selecting any PO line that still has stock.

---

# 5.10 Customer management

## Purpose

Store customer details for sales, invoices, payments, returns, advances, and reports.

## User role

All users.

## Main user flow

1. User creates customer from customer screen or sale screen.
2. User enters customer name and phone.
3. User optionally enters address.
4. Customer is saved and available for future sales.

## Business rules

* New customers created from sale screen are retained for future sales.
* Customer phone number is required.
* Customer phone number must be unique.
* Phone number uniqueness should be checked after normalizing formatting.
* Only one phone number per customer.
* Address is optional.
* Customer can have outstanding balance and advance balance at the same time.

## Required inputs

* Customer name
* Phone
* Optional address

## Validation rules

* Name required.
* Phone required.
* Phone must be unique after normalization.
* Address can be empty.

## Success behavior

Customer is saved and available in sales.

## Failure or blocked behavior

* Duplicate normalized phone blocks save.
* Missing name or phone blocks save.

## Edge cases

* Customer created during sale should persist for future use.
* Customer may have both outstanding balance and advance balance.

Status: **Confirmed**

---

# 5.11 Customer advances

## Purpose

Track customer overpayments or advance payments and allow them to be settled against sales.

## User role

All users.

## Main user flow

1. User records customer advance or system creates it from overpayment/refund choice.
2. When customer is selected in sale, system shows advance and outstanding balance.
3. User chooses whether to settle advance against the sale.
4. If not settled, available advance can be shown on invoice as information.

## Business rules

* Customer advance can be recorded.
* Customer overpayment becomes customer advance.
* Customer advance can be refunded.
* Customer advance is not automatically settled.
* User is asked per SO whether to settle advance or leave it as is.
* If advance is not settled, it should appear as available advance on invoice if configured.
* If customer advance is settled, it remains in transaction history, not necessarily on invoice.
* Customer can have outstanding balance and advance at the same time.

## Required inputs

* Customer
* Amount
* Date
* Payment method
* Instrument details for non-cash payments

## Validation rules

* Advance amount must be greater than zero.
* Advance settlement cannot exceed available advance.
* Advance cannot be settled against draft sale.

## Success behavior

Customer advance balance updates.

## Failure or blocked behavior

* Cannot settle more than available advance.
* Cannot settle advance against draft sale.

## Edge cases

* Customer overpayment automatically creates advance.
* Cancelled sale payment can be refunded or moved to customer advance.
* Sales return extra payment can be refunded or moved to customer advance.

Status: **Confirmed**

---

# 5.12 Sales

## Purpose

Allow the user to sell purchased products, manage stock deduction, discounts, margin, payments, invoices, cancellations, and edits.

## User role

All users.

## Main user flow

1. User opens sales screen.
2. User selects existing customer or creates new customer.
3. User adds product lines.
4. User chooses base unit or alternative unit per line.
5. User enters quantity and unit price.
6. User adds line discount or order discount if needed.
7. System checks stock.
8. System shows margin when user chooses to unhide it.
9. User records no payment, partial payment, or full payment.
10. User saves sale or draft.
11. Invoice can be generated for confirmed sale.

## Business rules

* Only purchased products can be sold.
* Product must have available stock.
* Negative stock is not allowed.
* If stock is insufficient, sale should be saved as draft instead of confirmed.
* Draft sale does not reserve stock.
* Draft sale cannot receive payment.
* Draft sale cannot generate invoice.
* User can sell in base unit or alternative unit in a single product line.
* If both base and alternative units are needed, user must add separate product lines.
* Discounts are fixed money amounts, not percentages.
* Discounts can be line-level or order-level.
* Margin is hidden by default.
* User can unhide margin on the sale screen.
* Margin is calculated using FIFO cost.
* Sale below cost is allowed with warning.
* Negative margin is allowed with warning.
* No special permission required for negative-margin sale.
* Sale can be edited after invoice generation.
* Sale can be edited after payment.
* Sale cannot be deleted.
* Sale can be cancelled by changing status.
* Cancelled sale restocks inventory through reversal entry.
* Cancelled sale can be reactivated.
* Partial cancellation is not allowed.

## Required inputs

* Customer
* Product
* Quantity
* Unit
* Unit sale price
* Optional line discount
* Optional order discount
* Payment option
* Payment method and details if payment is made

## Validation rules

* Confirmed sale requires customer.
* Confirmed sale requires valid product lines.
* Quantity must be greater than zero.
* Quantity max 2 decimals.
* Stock must be available.
* Sale below cost shows warning.
* Draft sale cannot receive payment.
* Draft sale cannot generate invoice.

## Success behavior

* Confirmed sale reduces stock.
* Customer balance updates.
* Payment status updates.
* Invoice can be generated.
* Margin can be viewed if user chooses.

## Failure or blocked behavior

* If stock is insufficient, sale becomes draft.
* If required payment fields are missing, payment cannot be saved.
* Sale cannot be deleted.
* Partial cancellation is blocked.

## Edge cases

* Cancelled sale restocks inventory.
* Cancelled sale payment is either refunded or moved to customer advance.
* Edited sale after invoice gets a new invoice number.
* Old invoice versions are kept but not printable.
* If edited paid sale total increases, difference becomes outstanding unless paid fully.
* If edited paid sale total decreases, user chooses refund or customer advance.
* Sale edit after sales return is allowed.

Status: **Mostly clear**

---

# 5.13 Sales payments

## Purpose

Allow customer payments against sales, including cash, bank transfer, and cheque.

## User role

All users.

## Main user flow

1. User creates sale or opens unpaid/partially paid sale.
2. User selects payment amount.
3. User selects payment method.
4. User enters required payment details.
5. Payment is saved.
6. Sale/customer balance updates.

## Business rules

* Initial payment can be:

  * Zero
  * Partial
  * Full
* Payment methods:

  * Cash
  * Bank transfer
  * Cheque
* For non-cash payment, user must enter bank/account/instrument details.
* Customer bank details are not stored as reusable customer profile accounts.
* Customer payment bank details are stored in SO/payment transaction history.
* Cheque payment starts as posted.
* Posted means cheque details are recorded.
* Cheque must be manually marked as cleared.
* If cheque bounces, cheque status becomes bounced.
* The remaining/unsettled amount from bounced cheque should be added back to customer outstanding balance.
* If customer overpays, extra amount becomes customer advance.

## Required inputs

For cash:

* Sale
* Amount
* Date

For cheque/bank transfer:

* Sale
* Amount
* Bank name
* Account number
* Instrument number
* Date

## Validation rules

* Draft sale cannot receive payment.
* Payment amount must be greater than zero.
* Non-cash fields are required.
* Payment over sale balance creates customer advance.

## Success behavior

* Payment is recorded.
* Sale payment status updates.
* Customer balance updates.
* Cheque can later be marked cleared or bounced.

## Failure or blocked behavior

* Payment blocked for draft sale.
* Non-cash payment blocked if required details are missing.

## Edge cases

* Bounced cheque increases customer outstanding by the unsettled amount.
* Overpayment becomes advance.
* Payment edits/cancellations should be audited.

Status: **Mostly clear**

Minor note:

* The exact wording of cheque bounce balance adjustment should be implemented as “add the unsettled bounced amount back to outstanding balance.”

---

# 5.14 Sales returns

## Purpose

Allow customers to return sold products and adjust stock, customer balance, refunds, or customer advance.

## User role

All users.

## Main user flow

1. User opens sales return screen.
2. User selects sale.
3. User selects sold product line.
4. User enters return quantity.
5. System validates returned quantity.
6. System restocks inventory.
7. System adjusts sale/customer balance.
8. If money is owed to customer, user chooses refund or customer advance.

## Business rules

* Only sold products can be returned.
* Partial returns are allowed.
* Return quantity cannot exceed sold quantity minus already returned quantity.
* Sales return can happen at any payment stage:

  * Unpaid
  * Partially paid
  * Fully paid
* Multiple returns against same sale are allowed.
* Sales return can be edited or cancelled.
* Returned items are treated as usable stock and restocked automatically.
* Damaged items are not handled through sales return.
* Damaged inventory is handled separately through expenses/damaged inventory adjustment.
* Damaged item will not be returned through the sales return flow.

## Payment adjustment rules

If sale is unpaid:

* Customer receives nothing.
* Sale total/outstanding is adjusted.

If sale is partially paid:

* Return amount adjusts unpaid balance first.
* If paid amount becomes greater than revised sale total, user chooses:

  * Refund customer
  * Add to customer advance

If sale is fully paid:

* User chooses:

  * Refund customer
  * Add to customer advance

## Required inputs

* Sale
* Product line
* Quantity
* Date
* Refund/advance choice if money is owed
* Refund method if refund selected

## Validation rules

* Return quantity must be greater than zero.
* Return quantity cannot exceed sold minus already returned.
* Return quantity max 2 decimals.
* Draft sale cannot have return.
* Refund details required if refund is selected.

## Success behavior

* Inventory restocks.
* Customer balance updates.
* Refund or customer advance is recorded if needed.

## Failure or blocked behavior

* Return blocked if quantity exceeds allowed return quantity.
* Return blocked if sale/product line is invalid.

## Edge cases

* Pending/posted cheque sales return should follow the same cash-based sale adjustment rules.
* Damaged goods are handled outside sales return through expense/damaged inventory adjustment.

Status: **Confirmed**

---

# 5.15 Sale invoices

## Purpose

Generate fixed-format sale invoices for confirmed sales.

## User role

All users.

## Main user flow

1. User confirms sale.
2. User generates invoice.
3. System assigns unique invoice number.
4. Invoice shows sale details and payment status.
5. User prints latest invoice version if needed.

## Business rules

* Invoice format is fixed.
* Invoice number must be unique.
* Invoice number is generated when invoice is generated.
* Invoice should show:

  * Product name
  * Quantity
  * Unit price
  * Line total
  * Discount, if applied
  * Customer phone
  * Customer address
  * Payment status
* Order discount appears only if applied.
* Line discount column appears only if at least one product line has line discount.
* Previous balance is shown by default, but this should be configurable.
* Customer advance settlement should stay in transaction history, not on invoice.
* If sale is edited after invoice generation, system creates a new invoice number.
* Old invoice versions are kept for record/audit.
* Only latest invoice version is printable.
* Old invoice versions are view-only.
* Cancelled invoices are not printable.
* Cancelled invoices remain visible in records.

## Required data

* Invoice number
* Invoice date
* Customer details
* Sale lines
* Discounts
* Payment status
* Previous balance, depending on configuration

## Validation rules

* Draft sale cannot generate invoice.
* Invoice number must be unique.
* Only latest invoice can be printed.
* Cancelled invoice cannot be printed.

## Success behavior

Invoice is generated and latest version can be printed.

## Failure or blocked behavior

* Draft sale invoice generation blocked.
* Cancelled invoice printing blocked.
* Old invoice version printing blocked.

## Edge cases

* Edited sale creates a new invoice number.
* Old versions remain viewable but not printable.
* Cancelled invoice remains in records but cannot be printed.

Status: **Confirmed**

---

# 5.16 Quotations

## Purpose

Allow users to create sale-like quotations without payments.

## User role

All users.

## Main user flow

1. User opens quotation screen.
2. User enters quotation details using sale-like layout.
3. User adds customer and products.
4. User saves quotation.
5. User may edit or cancel quotation.
6. User may convert quotation into sale once.

## Business rules

* Quotation uses same window/layout as sales.
* Quotation has no payment options.
* Quotation does not reserve stock.
* Quotation can be edited.
* Quotation can be cancelled.
* Quotation does not expire.
* Quotation has no expiry date.
* Quotation can be converted to sale.
* On conversion, payment options become available.
* Quotation can be converted only once.
* Original quotation should not remain as an active separate quotation after conversion.
* When converting to sale, prices/details should be editable so user can decide.

## Required inputs

* Customer or customer details
* Product lines
* Quantity
* Unit
* Unit price
* Optional discount

## Validation rules

* No payment allowed on quotation.
* Quotation conversion allowed only once.
* Since quotation does not reserve stock, stock must be checked again when converting to sale.

## Success behavior

Quotation is saved, editable, cancellable, and convertible to sale.

## Failure or blocked behavior

* Payment cannot be recorded on quotation.
* Already converted quotation cannot be converted again.
* If stock is insufficient at conversion, sale should follow draft/stock rules.

## Edge cases

* Quoted prices may be edited before final sale.
* Quotation does not affect inventory.

Status: **Confirmed**

---

# 5.17 Expenses

## Purpose

Track business expenses and support damaged inventory adjustment through expense categories.

## User role

All users.

## Main user flow

1. User opens expense screen.
2. User selects or creates category.
3. User enters expense name, payee, amount, and date.
4. User records expense.
5. Expense appears in expense history/report.

## Business rules

* Every expense needs a category.
* If category does not exist, user can create it.
* Category is stored for future use.
* Expense payment is cash only.
* No attachments or receipts are required.
* Recurring expenses are not needed.
* Taxes are not included.
* Expense categories cannot be edited or deleted if expenses exist under them.
* If category has old expenses, it stays as is.

## Required inputs

* Expense name
* Category
* Payee name
* Amount
* Date, default today
* Payment method: cash only

## Validation rules

* Expense name required.
* Category required.
* Payee required.
* Amount required and must be greater than zero.
* Date required.
* Payment method is cash only.

## Success behavior

Expense is saved and appears in expense history/report.

## Failure or blocked behavior

* Missing required fields block save.
* Used category cannot be edited or deleted unless related expenses are deleted.

## Edge cases

* New category can be created during expense entry.
* Used categories remain unchanged.

Status: **Confirmed**

---

# 5.18 Damaged inventory adjustment

## Purpose

Handle damaged inventory as an expense that also reduces stock.

## User role

All users.

## Main user flow

1. User opens expense/damaged inventory flow.
2. User selects damaged inventory category.
3. User selects product.
4. User enters quantity, unit, cost, and reason.
5. System checks available stock.
6. System calculates cost using FIFO.
7. System reduces inventory immediately.
8. System records expense and inventory stock movement.

## Business rules

* Damaged inventory is handled through expenses.
* Damaged inventory must have its own category.
* Damaged inventory reduces stock immediately.
* Damaged inventory uses FIFO cost.
* Damaged inventory can only be recorded from available stock.
* Damaged inventory should appear in:

  * Expense history/report
  * Inventory stock movement history as stock reduction
* Damaged returned goods are not handled inside sales return.
* A damaged item will not be returned through the sales return process.

## Required inputs

* Product
* Quantity
* Unit
* Cost
* Reason
* Category
* Date
* Payee/name as required by expense flow

## Validation rules

* Product required.
* Quantity required and must be greater than zero.
* Quantity cannot exceed available stock.
* Unit required.
* Reason required.
* Category required.
* Stock cannot go negative.

## Success behavior

* Expense is created.
* Inventory is reduced.
* Stock movement entry is created.

## Failure or blocked behavior

* Blocked if stock is unavailable.
* Blocked if required fields are missing.

## Edge cases

* Damaged stock should reduce inventory even though it is recorded through expense.
* It should be visible in both expense and inventory history.

Status: **Confirmed**

---

# 5.19 Reports

## Purpose

Provide business visibility into inventory, sales, purchases, payments, expenses, customers, vendors, aging, and profit/loss.

## User role

All users.

## Required report areas

The application should include reports for:

* Aging
* Inventory
* Expense
* Financial
* Sales
* Purchase
* Payments
* Individual customer
* Individual vendor
* Profit and loss between two dates

## Business rules

* Reports should show current data.
* If old payments are edited later, reports should reflect current data.
* Audit trail should still show previous payment versions.
* Profit reports should use FIFO cost.
* Purchase discounts affect profit.
* Damaged inventory should affect expenses and stock.
* Cancelled sales should affect stock through reversal entries.
* Old invoice versions and payment edits should remain visible in audit.

## Required data

Depends on report type, but generally includes:

* Date range
* Customer/vendor/product filters where relevant
* Transaction totals
* Payment status
* Outstanding balance
* Advance balance
* Stock quantity
* Stock value
* Profit/loss values

## Validation rules

* Date range required for reports that compare periods.
* Profit/loss report requires start and end date.
* Reports should not include draft transactions as real stock/payment activity.

## Success behavior

Reports show current business data and balances.

## Failure or blocked behavior

* Invalid date range blocks report generation.
* Missing required report filter blocks report generation where needed.

## Edge cases

* Edited payments update reports but remain visible in audit.
* Cancelled payments are hidden from normal lists but visible in audit.
* Old invoices are view-only.
* Cancelled invoices are visible in records but not printable.

Status: **Mostly clear**

Needs confirmation:

* Exact columns and filters for each report are not fully defined.

---

# 5.20 Audit history

## Purpose

Keep traceability for edited, cancelled, or versioned business records.

## User role

All users.

## Main user flow

1. User edits or cancels payment/sale/invoice-related record.
2. System updates current business data.
3. System keeps old version or change trail in audit history.
4. Users can view audit trail.

## Business rules

* Payment edits keep old version in audit.
* Cancelled payments disappear from normal lists but remain in audit.
* Old invoice versions are kept.
* Old invoice versions are view-only.
* Latest invoice is the only printable version.
* Reports show current data, but audit shows changes.
* Cancelled invoices remain visible in records but cannot be printed.

## Required data

* Record type
* Record reference
* Old value/version
* New value/version
* Date/time of change
* User, if user tracking exists

## Validation rules

* Audit trail should not be deleted through normal business flows.
* Cancelled/edited records should remain traceable.

## Success behavior

Business data updates while old history remains visible.

## Failure or blocked behavior

* Audit data should not disappear when payment disappears from normal list.

## Edge cases

* Payment edited after report generation updates reports but keeps trail.
* Sale edited after invoice generation creates new invoice version.

Status: **Confirmed**

---

# 6. Key user flows

## 6.1 Product setup flow

1. Add product.
2. Select base unit.
3. Add alternative units if needed.
4. Add conversion factors.
5. Save product.
6. Product becomes available for purchase.

---

## 6.2 Purchase flow

1. Select or add vendor.
2. Add products.
3. Enter quantity, unit, purchase price, and sale price.
4. Add discounts if needed.
5. Save as draft or confirm PO.
6. If draft, no stock/payment effect.
7. If confirmed, stock increases.
8. Record no/partial/full/extra payment.
9. Extra payment becomes vendor advance.

---

## 6.3 Purchase payment flow

1. Select specific PO.
2. Enter payment amount.
3. Select cash, cheque, or bank transfer.
4. Enter required details.
5. Save payment.
6. PO and vendor balance update.

---

## 6.4 Purchase return flow

1. Select PO and PO line.
2. Enter quantity.
3. System checks available stock.
4. Inventory reduces.
5. PO total and vendor balance update.
6. If extra paid amount exists, choose refund or vendor advance.

---

## 6.5 Sale flow

1. Select or create customer.
2. Add products.
3. Choose unit per line.
4. Enter quantity and price.
5. Add discounts if needed.
6. System checks stock.
7. If stock is available, sale can be confirmed.
8. If stock is insufficient, sale becomes draft.
9. Record no/partial/full payment.
10. Generate invoice.

---

## 6.6 Sale cancellation flow

1. User changes sale status to cancelled.
2. Inventory is restocked through reversal entry.
3. Existing payment is either refunded or moved to customer advance.
4. Cancelled invoice is not printable.
5. Sale can be reactivated.

---

## 6.7 Sales return flow

1. Select sale.
2. Select sold product.
3. Enter return quantity.
4. System checks sold minus already returned quantity.
5. Inventory restocks.
6. Customer balance adjusts.
7. If refund is due, choose refund or customer advance.

---

## 6.8 Quotation flow

1. Create quotation using sale-like screen.
2. No payment options.
3. Save quotation.
4. Edit or cancel if needed.
5. Convert to sale once.
6. On conversion, check stock and allow edits.

---

## 6.9 Damaged inventory flow

1. Open expense/damaged inventory flow.
2. Select damaged inventory category.
3. Select product, quantity, unit, cost, reason.
4. System checks stock.
5. Stock reduces.
6. Expense record is created.
7. Inventory history shows stock reduction.

---

# 7. Validation and error-handling rules

| Situation                                  | Required behavior                                          |
| ------------------------------------------ | ---------------------------------------------------------- |
| Product missing during purchase            | Block confirmed purchase and show “Product doesn’t exist.” |
| Product not purchased during sale          | Block confirmed sale or keep as draft                      |
| Stock insufficient during sale             | Save as draft; do not reduce stock                         |
| Draft purchase                             | No inventory effect, no payment                            |
| Draft sale                                 | No stock reservation, no payment, no invoice               |
| Negative stock                             | Always blocked                                             |
| Sale below cost                            | Allow with warning                                         |
| Negative margin                            | Allow with warning                                         |
| Missing unit conversion factor             | Block product save                                         |
| Used base unit change                      | Block                                                      |
| Used alternative unit deactivate/edit      | Block                                                      |
| Used vendor bank account delete/inactivate | Block                                                      |
| Unused vendor bank account delete          | Allow                                                      |
| Missing non-cash instrument number         | Block payment save                                         |
| Customer duplicate phone                   | Block after phone normalization                            |
| Return quantity too high                   | Block                                                      |
| Payment over purchase total                | Add extra to vendor advance                                |
| Customer overpayment                       | Add extra to customer advance                              |
| Cancelled payment                          | Hide from normal list, keep in audit                       |
| Old invoice version                        | View only, not printable                                   |
| Cancelled invoice                          | Visible in records, not printable                          |
| Damaged inventory quantity unavailable     | Block                                                      |
| Invalid report date range                  | Block report generation                                    |

---

# 8. Permissions and access rules

For the first version:

* All users have equal access.
* No admin-only approval is required.
* All users can edit/cancel payments.
* All users can proceed with negative-margin sales after warning.
* All users can view inventory and reports.
* All users can view audit history.
* Margin is hidden by default but can be unhidden by the user.

Status: **Confirmed**

---

# 9. Edge cases

## Product and units

* Multiple alternative units allowed.
* Used units cannot be changed.
* Conversion values limited to 2 decimals.

## Inventory

* Cancelled sales create reversal entries.
* Damaged inventory creates stock reduction entries.
* Drafts do not appear as real stock movements.

## Purchases

* Same product can appear multiple times with different costs.
* Each different purchase price becomes separate FIFO layer.
* Purchase discounts affect profit, but exact allocation still needs confirmation.

## Purchase returns

* Multiple returns allowed if stock remains.
* User selects PO line.
* Purchase return uses LIFO.
* If extra paid amount exists, user chooses refund or vendor advance.

## Sales

* Stock shortage creates draft.
* Sale can be edited after payment/invoice.
* Sale can be edited after sales return.
* Sale cannot be deleted.
* Cancelled sale can be reactivated.

## Sales payments

* Customer cheque can be posted, cleared, or bounced.
* Bounced cheque adds unsettled amount back to customer outstanding.

## Sales returns

* Returned quantity cannot exceed sold minus already returned.
* Damaged goods are not returned through sales return.
* Damaged inventory is handled through expense/damaged inventory flow.

## Invoices

* New invoice number after sale edit.
* Old invoice versions kept but view-only.
* Latest invoice only is printable.

## Expenses

* Expenses are cash only.
* Damaged inventory is recorded as expense and stock reduction.

---

# 10. Items that still need confirmation

These are the only genuinely unresolved items that may block precise development.

## 10.1 Purchase discount allocation

Confirmed:

* Purchase discounts affect profit.
* Line discount does not directly reduce product purchase cost.
* Order-level discount subtracts from total bill.

Needs confirmation:

* How exactly should discounts be allocated into FIFO cost layers for product-level profit and inventory valuation?

This matters for accurate profit reporting.

Status: **Needs confirmation**

---

## 10.2 Purchase return LIFO with selected PO line

Confirmed:

* Purchase returns use LIFO.
* User selects original PO line.
* Latest answer says user can select any PO line if products are still in stock.

Needs confirmation:

* If the selected PO line is not the latest available layer, should LIFO still override it, or should the selected PO line be honored as long as stock is available?

Status: **Needs confirmation**

---

## 10.3 Report layouts

Confirmed report types exist.

Needs confirmation:

* Exact columns, filters, grouping, and export requirements for each report.

This does not block core transaction features but blocks final report implementation.

Status: **Needs confirmation**

---

# 11. Application summary table

| Area           | Feature                   | User role | What it does                                                    | Key rules                                                   | Status             |
| -------------- | ------------------------- | --------- | --------------------------------------------------------------- | ----------------------------------------------------------- | ------------------ |
| Products       | Product creation          | All users | Adds products for purchase/sale                                 | Product must exist before purchase; purchased before sale   | Confirmed          |
| Products       | Base unit                 | All users | Defines main stock unit                                         | Cannot change after transactions                            | Confirmed          |
| Products       | Alternative units         | All users | Allows selling/buying in other units                            | Conversion factor required; max 2 decimals                  | Confirmed          |
| Products       | Multiple alt units        | All users | Allows more than one alt unit                                   | Each alt unit has own conversion factor                     | Confirmed          |
| Inventory      | Current stock             | All users | Shows available stock                                           | Current stock only; no negative stock                       | Confirmed          |
| Inventory      | Stock valuation           | All users | Shows stock value                                               | FIFO except purchase returns                                | Confirmed          |
| Inventory      | Stock movements           | All users | Shows stock changes                                             | Returns and cancellation reversals visible                  | Confirmed          |
| Inventory      | Related payments          | All users | Shows payment references                                        | Separate tab from stock movements                           | Confirmed          |
| Vendors        | Vendor profile            | All users | Stores vendor details                                           | Company, rep, address, phone required                       | Confirmed          |
| Vendors        | Vendor bank accounts      | All users | Stores saved vendor accounts                                    | Bank name and account number required                       | Confirmed          |
| Vendors        | Temporary accounts        | All users | Stores one-off payment account details                          | Stored in PO/payment history, not vendor profile            | Confirmed          |
| Vendors        | Vendor advances           | All users | Tracks extra paid vendor balance                                | User chooses whether to apply to PO                         | Confirmed          |
| Purchases      | Draft PO                  | All users | Saves incomplete purchase                                       | No stock effect; no payment                                 | Confirmed          |
| Purchases      | Confirmed PO              | All users | Records purchase and increases stock                            | Stock increases on PO confirmation                          | Confirmed          |
| Purchases      | Purchase discounts        | All users | Reduces purchase bill and affects profit                        | Exact cost allocation unclear                               | Needs confirmation |
| Purchases      | Purchase payment          | All users | Pays a specific PO                                              | One payment applies to one PO only                          | Confirmed          |
| Purchases      | Vendor cheque payment     | All users | Pays vendor by cheque                                           | Marked paid immediately                                     | Confirmed          |
| Purchases      | Purchase return           | All users | Returns purchased stock                                         | LIFO; selected PO line; available stock required            | Needs confirmation |
| Customers      | Customer profile          | All users | Stores customer details                                         | One normalized unique phone number                          | Confirmed          |
| Customers      | Customer advance          | All users | Tracks overpayment/advance                                      | User chooses settlement per SO                              | Confirmed          |
| Sales          | Draft sale                | All users | Saves incomplete/unavailable-stock sale                         | No stock reservation; no payment; no invoice                | Confirmed          |
| Sales          | Confirmed sale            | All users | Sells purchased products                                        | Stock required; FIFO margin                                 | Confirmed          |
| Sales          | Negative margin           | All users | Allows below-cost sale                                          | Warning required; no admin approval                         | Confirmed          |
| Sales          | Sale cancellation         | All users | Cancels sale without deletion                                   | Restock through reversal; refund or advance payment         | Confirmed          |
| Sales          | Sale edit                 | All users | Edits sale after payment/invoice                                | New invoice number; old versions kept                       | Mostly clear       |
| Sales payments | Cash payment              | All users | Records cash payment                                            | Not allowed on draft sale                                   | Confirmed          |
| Sales payments | Bank transfer             | All users | Records bank payment                                            | Bank/account/instrument details required                    | Confirmed          |
| Sales payments | Cheque payment            | All users | Records posted cheque                                           | Manual clear/bounce status                                  | Confirmed          |
| Sales returns  | Sales return              | All users | Returns sold usable stock                                       | Cannot exceed sold minus returned                           | Confirmed          |
| Sales returns  | Refund/advance choice     | All users | Handles extra paid amount                                       | User chooses refund or customer advance                     | Confirmed          |
| Invoices       | Invoice generation        | All users | Generates fixed invoice                                         | Unique number generated on invoice creation                 | Confirmed          |
| Invoices       | Edited sale invoice       | All users | Creates new invoice after edit                                  | Old versions view-only; latest printable                    | Confirmed          |
| Invoices       | Cancelled invoice         | All users | Keeps cancelled invoice record                                  | Visible but not printable                                   | Confirmed          |
| Quotations     | Create quotation          | All users | Creates sale-like quotation                                     | No payments; no stock reservation                           | Confirmed          |
| Quotations     | Convert quotation         | All users | Converts quotation to sale                                      | Conversion only once; editable before sale                  | Confirmed          |
| Expenses       | Normal expense            | All users | Records business expense                                        | Category, payee, amount, date required; cash only           | Confirmed          |
| Expenses       | Expense categories        | All users | Creates reusable categories                                     | Used category cannot be edited/deleted                      | Confirmed          |
| Damaged stock  | Damaged inventory expense | All users | Records damaged stock as expense                                | Reduces stock; FIFO cost; available stock only              | Confirmed          |
| Reports        | Business reports          | All users | Shows sales, purchase, inventory, payments, expense, aging, P/L | Current data; audit trail visible                           | Mostly clear       |
| Audit          | Audit history             | All users | Keeps old versions and edits                                    | Payment edits, invoice versions, cancelled payments tracked | Confirmed          |

