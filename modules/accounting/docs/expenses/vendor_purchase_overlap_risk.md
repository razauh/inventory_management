# Audit: Vendor and Purchase Overlap Risk

This document details the financial and technical risks associated with data entry overlap between general free-text expenses and inventory/vendor purchase payments in the application.

## 1. Overlap Risk Description

In the current schema, two independent pathways exist for recording cash outflows/expenditures:

1. **General Expenses**: Entered via the Expenses module. These are recorded directly in the `expenses` table as standalone rows.
2. **Vendor Purchases / Payments**: Recorded via the Purchases module. An inventory purchase header is created in `purchases`, and corresponding payments are stored in `purchase_payments`.

Because the `expenses` table contains only free-text columns, there is no foreign key or logical link constraint mapping expenses to vendors or purchases. This introduces the following risks:
- **Double-Counting**: A user might record a cash payment to a supplier as a general operating expense, while also recording the corresponding inventory invoice in the purchases ledger (with its own purchase payment). This double-counts the expenditure, artificially depressing profit figures.
- **Reporting Inconsistencies**: Financial reports (such as the Income Statement / Profit & Loss) extract category totals from `expenses` and stock valuations/purchases independently. Without coordination, the system cannot distinguish between operating overhead (e.g. office supplies, rent) and direct inventory-related expenditures.

## 2. Technical Details & Code References

### Database Schema Overlap

- **General Expenses Table** (`database/schema.py` line 108):
  ```sql
  CREATE TABLE IF NOT EXISTS expenses (
      expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
      description TEXT NOT NULL,
      amount REAL NOT NULL,
      date TEXT NOT NULL,
      category_id INTEGER,
      FOREIGN KEY (category_id) REFERENCES expense_categories(category_id)
  )
  ```
  Note that there is no `vendor_id` or `purchase_id` field.

- **Purchase & Payment Tables** (`database/schema.py` lines 162 & 585):
  ```sql
  CREATE TABLE IF NOT EXISTS purchases (
      purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
      vendor_id INTEGER NOT NULL,
      purchase_date TEXT NOT NULL,
      ...
  )

  CREATE TABLE IF NOT EXISTS purchase_payments (
      payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
      purchase_id INTEGER NOT NULL,
      amount REAL NOT NULL,
      payment_date TEXT NOT NULL,
      ...
  )
  ```

### Code Implementation Points

- **Expenses Management**:
  - `database/repositories/expenses_repo.py` (`ExpensesRepo` writes/reads)
  - `modules/accounting/current_rules/expense_rules.py` (Centralized facade logic)
- **Purchases & Vendor Payments**:
  - `database/repositories/purchases_repo.py` (`PurchasesRepo`)
  - `database/repositories/purchase_payments_repo.py` (`PurchasePaymentsRepo`)

## 3. Potential Mitigations

To prevent transaction double-counting in future updates:
1. **Schema Extension**: Add nullable `vendor_id` and `purchase_id` columns to the `expenses` table. This allows tracing direct vendor-associated overhead (like transport/freight costs) to the originating purchase invoice.
2. **UI Constraints**: Prevent users from selecting "Vendor Payment" or similar categories in the general expense screen without supplying a specific vendor account link.
3. **Cross-Validation**: Implement validator alerts in `AccountingService` to notify users if an expense amount and date matches a recently entered purchase payment.
