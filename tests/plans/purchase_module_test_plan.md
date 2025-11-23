inside the sales module 
/home/pc/Desktop/inventory_management/modules/sales
1: i need you to update the SO window, right now there is only x button on it, i need you to update it with minimize/maximize button, don't try to implement anything new, it's been already implemented inside the new PO window /home/pc/Desktop/inventory_management/modules/purchase/form.py
so i just need you to go ahead and copy it from there, but remember do not change the location of the subtotla, line total, order discount, total discount, and total 
2: i need you to restructure the SO window just like the PO window, bring the payment section on the right side, keep the overall width of it small, probably not more than 20-25% of it, 
3: when the payment method bank transfer is selected there is dropdown that is supposed to show the saved company bank accounts, but right now its not showing anything, its stuck like there are no values in the DB but if you look into the DB there are values in it,
4: inside product line the first column # has too big of the width, reduce it, also reduce the width of other columns with numeric values, these dont need that much and around 50% increased the width of the product column
5: reduce the width of input boxes of the values of customer, contact, date, order discount, Notes, 
6: increase the font sizes of the subtotal, line total, order discount, total discount, and total for better visibility

before doing all this, i need you to implement tests to verify all these changes by creating a new dir inside test, named sales, make sure these test are implemented first before you try to implement the actual code changes inside the application and then run those tests to verify the correctness


# Comprehensive Test Plan: Purchase Module

## 1. Introduction & Scope

This document outlines the testing strategy and plan for the **Purchase Module**. The goal is to ensure the module is robust, reliable, and meets all functional requirements. The scope of this plan covers the entire lifecycle of a purchase, including:

*   Creating and editing Purchase Orders (POs).
*   Managing initial and subsequent payments.
*   Handling purchase returns.
*   UI/UX of all related forms and views.
*   Business logic and validation.
*   Database integrity.

## 2. Test Strategy

We will employ a multi-layered testing strategy to ensure comprehensive coverage:

*   **Unit Testing:** To test individual functions and methods in isolation (e.g., validation logic, calculations).
*   **Integration Testing:** To test the interaction between different components, such as the controller, model, and database repositories.
*   **End-to-End (E2E) / UI Testing:** To test the application from the user's perspective, simulating real-world scenarios. This can be done manually or with an automated UI testing framework.

## 3. Test Cases

### 3.1. Purchase Order (PO) Form (`PurchaseForm`)

#### 3.1.1. UI/UX Testing

| Test Case ID | Description | Expected Result |
| :--- | :--- | :--- |
| PO-UI-001 | Open the "New PO" window. | The form opens with all fields in their default state. |
| PO-UI-002 | Check that the window has minimize, maximize, and close buttons. | All three buttons are present and functional. |
| PO-UI-003 | Resize the window. | All UI elements resize and re-flow gracefully. |
| PO-UI-004 | Add a new row to the items table. | A new, empty row is added, and the cursor is focused on the "Product" field. |
| PO-UI-005 | Delete a row from the items table using the "✕" button. | The selected row is removed, and the totals are updated. |
| PO-UI-009 | Click the "Print" button. | A PDF invoice is generated and opened for printing. |
| PO-UI-010 | Click the "Export to PDF" button. | A PDF invoice is saved to the "PIs" folder on the Desktop. |
| PO-UI-006 | Enter text in the "Vendor" dropdown. | A list of matching vendors appears. |
| PO-UI-007 | Select a vendor. | The vendor's name and ID are populated, and the "Vendor Balance" is displayed. |
| PO-UI-008 | Change the "Initial Payment" amount. | The payment details section enables/disables fields appropriately. |

#### 3.1.2. Data Validation

| Test Case ID | Description                                               | Expected Result                                                                     |
| :----------- | :-------------------------------------------------------- | :---------------------------------------------------------------------------------- |
| PO-DV-001    | Try to save a PO without selecting a vendor.              | A validation error message is displayed.                                            |
| PO-DV-002    | Try to save a PO without any items.                       | A validation error message is displayed.                                            |
| PO-DV-003    | Enter a non-numeric value in the "Qty" or "Price" fields. | The input should be rejected or flagged as invalid.                                 |
| PO-DV-004    | Enter a sale price lower than the buy price.              | The sale price field is marked as invalid, and a validation error is shown on save. |
| PO-DV-005    | Enter a negative initial payment amount.                  | A validation error message is displayed.                                            |

#### 3.1.3. Initial Payment Permutations

This matrix covers the various combinations for the "Initial Payment" section when creating or editing a PO.

| Test Case ID | Payment Method | Amount | Company Bank Acct | Vendor Bank Acct | Instrument # | Temp Bank Details | Expected Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| PO-IP-001 | `Cash` | > 0 | N/A | N/A | N/A | No | Success |
| PO-IP-002 | `Bank Transfer` | > 0 | Selected | Selected | Provided | No | Success |
| PO-IP-003 | `Bank Transfer` | > 0 | Not Selected | Selected | Provided | No | Validation Error |
| PO-IP-004 | `Bank Transfer` | > 0 | Selected | Not Selected | Provided | No | Validation Error |
| PO-IP-005 | `Bank Transfer` | > 0 | Selected | Not Provided | No | Validation Error |
| PO-IP-006 | `Bank Transfer` | > 0 | Selected | "Temporary" | Provided | Provided | Success |
| PO-IP-007 | `Bank Transfer` | > 0 | Selected | "Temporary" | Provided | Not Provided | Validation Error |
| PO-IP-008 | `Cheque` | > 0 | Selected | N/A | Provided | No | Success |
| PO-IP-009 | `Cheque` | > 0 | Not Selected | N/A | Provided | No | Validation Error |
| PO-IP-010 | `Cross Cheque` | > 0 | Selected | Selected | Provided | No | Success |
| PO-IP-011 | `Cash Deposit` | > 0 | N/A | Selected | Provided | No | Success |
| PO-IP-012 | `Other` | > 0 | N/A | N/A | N/A | No | Success |
| PO-IP-013 | Any | 0 | N/A | N/A | N/A | No | Success (no payment recorded) |

### 3.2. Purchase Return Form (`PurchaseReturnForm`)

#### 3.2.1. UI/UX Testing

| Test Case ID | Description | Expected Result |
| :--- | :--- | :--- |
| PR-UI-001 | Open the "Return" window for a PO. | The form opens with a list of returnable items and quantities. |
| PR-UI-002 | Enter a return quantity greater than the returnable quantity. | The input is rejected or flagged as invalid. |
| PR-UI-003 | Select "Vendor Credit" as the settlement method. | The UI updates to show credit-related information. |
| PR-UI-004 | Select "Cash/Bank Refund" as the settlement method. | The UI updates to show payment-related fields. |

#### 3.2.2. Return Scenarios

| Test Case ID | Items Returned | Settlement Method | Notes | Expected Result |
| :--- | :--- | :--- | :--- | :--- |
| PR-RS-001 | Partial quantity of one item. | Vendor Credit | "Damaged item" | A purchase return is created, and the PO's returnable quantities are updated. A vendor credit is created. |
| PR-RS-002 | Full quantity of multiple items. | Cash/Bank Refund | "Wrong items delivered" | A purchase return is created, and the PO's returnable quantities are updated. A payment record for the refund is created. |
| PR-RS-003 | Try to return more than the returnable quantity. | N/A | N/A | A validation error is shown. |
| PR-RS-004 | Return items from a fully paid PO. | Vendor Credit | N/A | The return is processed, and a vendor credit is generated. |

### 3.3. Purchase Payment Dialog (`PurchasePaymentDialog`)

#### 3.3.1. UI/UX Testing

| Test Case ID | Description | Expected Result |
| :--- | :--- | :--- |
| PP-UI-001 | Open the "Payment" window for a PO. | The form opens with the remaining due amount pre-filled. |
| PP-UI-002 | Change the payment method. | The form fields update to reflect the requirements of the selected method. |

#### 3.3.2. Payment Method Permutations

This matrix is similar to the initial payment one and should be tested with the same rigor.

| Test Case ID | Payment Method | Amount | Expected Result |
| :--- | :--- | :--- | :--- |
| PP-PM-001 | `Cash` | Partial | A partial payment is recorded. PO status becomes "Partially Paid". |
| PP-PM-002 | `Bank Transfer` | Full | A full payment is recorded. PO status becomes "Paid". |
| PP-PM-003 | `Cheque` | Overpayment | An overpayment is recorded, and the user is prompted to convert the excess to vendor credit. |
| PP-PM-004 | `Vendor Credit` | Full or Partial | The vendor's credit balance is applied to the PO. |

### 3.4. Main Purchase View (`PurchaseView`)

| Test Case ID | Description | Expected Result |
| :--- | :--- | :--- |
| PV-UI-001 | Search for a PO by its ID. | The table filters to show only the matching PO. |
| PV-UI-002 | Search for a PO by vendor name. | The table filters to show POs from that vendor. |
| PV-UI-003 | Filter POs by "Paid" status. | The table shows only fully paid POs. |
| PV-UI-004 | Select a PO in the table. | The details and items panels update to show the correct information for the selected PO. |

### 3.5. Database Integrity

| Test Case ID | Description | Expected Result |
| :--- | :--- | :--- |
| DB-INT-001 | Create a new PO. | A new record is created in the `purchases` table, and records for each item are created in the `purchase_items` table. |
| DB-INT-002 | Add an initial payment. | A new record is created in the `purchase_payments` table, linked to the new PO. |
| DB-INT-003 | Edit a PO's items. | The `purchase_items` table is updated, and the `total_amount` in the `purchases` table is recalculated. |
| DB-INT-004 | Delete a PO. | [NOT IMPLEMENTED] All related records in `purchases`, `purchase_items`, and `purchase_payments` are deleted (or marked as inactive, depending on the desired behavior). |
| DB-INT-006 | Auto-apply vendor credit. | When a purchase is created/paid, any available vendor credit is automatically applied to the remaining balance. |
| DB-INT-005 | Record a return for vendor credit. | A new record is created in the `purchase_returns` table, and a new credit is added to the `vendor_advances` table. |