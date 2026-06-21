# Vendor + Purchase Accounting References Audit

## Scope

This is an audit-only document for current vendor/purchase accounting-related code references. It maps existing calculations, validations, queries, writes, displays, reports, templates, tests, and side effects connected to vendor and purchase flows.

No behavior has been changed. No code has been refactored. No accounting correctness decisions have been made. Existing behavior is documented as found so a later consolidation can move logic into `modules/accounting/` safely.

## Summary

- Total files inspected: 190 source/template/test files in the focused search set.
- Total relevant files found: 57 files with vendor/purchase accounting references.
- Total references found: 76 grouped references in the detailed map below.
- Highest-risk areas:
  - Purchase status and paid/advance rollups exist in both SQL triggers/views and Python repository methods.
  - Vendor credit balance and credit application are spread across `vendor_advances`, controllers, reports, and tests.
  - Purchase return value, refund, and credit-note behavior is split across inventory transactions, snapshots, repo code, schema triggers, and reports.
  - Bank/cash assumptions are enforced in forms, repositories, and schema triggers.
  - Invoice/report code has its own financial display math and fallback behavior.
- Areas needing follow-up:
  - Decide which current SQL views/triggers remain source of truth after consolidation.
  - Add characterization tests before moving any vendor balance, purchase outstanding, return, refund, or status logic.
  - Reconcile purchase invoice totals with purchase order/item discount behavior.
  - Document cash/bank ledger semantics for vendor payments, vendor advances, and supplier refunds.
- Behavior is scattered across `database/schema.py`, repositories, `modules/vendor/`, `modules/purchase/`, reporting modules, templates, widgets, and tests.

## Search Method

- Directories inspected:
  - `database/`
  - `database/repositories/`
  - `modules/vendor/`
  - `modules/purchase/`
  - `modules/inventory/`
  - `modules/expense/`
  - `modules/sales/`
  - `modules/reporting/`
  - `modules/payments/`
  - `modules/backup_restore/`
  - `resources/templates/`
  - `widgets/`
  - `utils/`
  - `tests/vendor/`
  - `tests/purchase/`
  - `tests/reporting/`
  - `tests/inventory/`
  - `tests/expense/`
  - `tests/payments/`
- Keywords searched:
  - `vendor`, `vendors`, `supplier`, `suppliers`, `purchase`, `purchases`, `payable`, `payables`, `outstanding`, `balance`, `paid`, `unpaid`, `partial`, `payment`, `payments`, `advance`, `advances`, `credit`, `debit`, `refund`, `return`, `returns`, `allocation`, `allocated`, `unallocated`, `fifo`, `bank`, `cash`, `cheque`, `check`, `cleared`, `pending`, `bounced`, `status`, `total`, `subtotal`, `discount`, `tax`, `freight`, `expense`, `ledger`, `statement`, `history`, `invoice`, `bill`, `receipt`, `due`, `overdue`, `opening`, `adjustment`, `settlement`, `reconcile`.
- Commands/tools used:
  - `git status --short`
  - `rg --files`
  - `rg -n -i` broad keyword searches
  - `rg -n` focused symbol/table searches
  - `sed -n` targeted file reads
  - `./.conda/bin/graphify query ...` for orientation only
- Intentionally skipped:
  - `data/`, `.logs/`, `logs/`, `.pytest_cache/`, `.conda/`, `.wheelhouse/`, `.wheelhouse-app/`, `graphify-out/`, `__pycache__/`, local DB/export/cache artifacts.
  - Reason: repository instructions say not to inspect local data/artifacts unless needed.

## High-Level Findings

### Vendor balances and statements

- Vendor credit balance is stored as a signed sum of `vendor_advances.amount`; positive rows grant credit, negative rows apply credit.
- `v_vendor_advance_balance` and `VendorAdvancesRepo.get_balance()` both expose vendor credit balance.
- Vendor statement builds payable balance separately in `VendorController.build_vendor_statement()` from purchases, payments, refunds, deposits, and applied credits.
- Vendor list/details hydrate balances from `VendorsRepo.vendor_balances()` and `VendorAdvancesRepo.get_balance()`.

### Purchase totals and outstanding amounts

- Purchase gross totals are calculated from `purchase_items.quantity * (purchase_price - item_discount) - order_discount`.
- Net totals after returns are exposed through `purchase_detailed_totals`.
- Remaining due is recalculated in multiple places as net total minus cleared direct payments minus applied vendor credit.
- `purchases.paid_amount`, `purchases.advance_payment_applied`, and `purchases.payment_status` are stored rollups maintained by triggers and repository methods.

### Vendor payments

- Vendor payments are written to `purchase_payments`.
- Current repo policy requires purchase payments to be cleared only.
- Overpayment can be converted into vendor credit in `PurchasePaymentsRepo.record_payment()`.
- Payment method, instrument, company bank, vendor bank, and temporary vendor bank metadata are captured in forms and persisted.

### Vendor advances and credits

- Vendor credit is written to `vendor_advances`.
- Manual credit/deposit and return credit are positive rows.
- Applied credit is a negative row with `source_type='applied_to_purchase'`.
- Payment metadata can be attached to vendor advance rows.

### Advance allocation/FIFO

- Vendor grant-credit preview allocates credit across open purchases in purchase date then purchase id order.
- Auto-application is orchestrated in `modules/vendor/controller.py`, not the repository.
- SQL triggers prevent overdraw and over-application.

### Purchase returns and supplier refunds

- Purchase returns are written as `inventory_transactions.transaction_type='purchase_return'`.
- Return value is snapshot-driven through `purchase_return_snapshots` and `purchase_return_valuations`.
- Settlement may produce `purchase_refunds` cash/bank inflow or `vendor_advances.source_type='return_credit'`.
- Return settlement logic also reinstates funded excess to vendor credit.

### Bank/cash/payment method effects

- `purchase_payments`, `vendor_advances`, and `purchase_refunds` all carry method, company bank, vendor bank, instrument, cleared date, and clearing state fields.
- Schema triggers enforce active company/vendor accounts and ownership.
- `v_bank_ledger` and `v_bank_ledger_ext` include vendor-side disbursements/refunds/advances.
- Reporting disbursement views use cleared vendor payments and cleared supplier refunds.

### Inventory effects from purchases/returns

- Purchase creation/update writes `inventory_transactions` for purchases.
- Purchase returns write `inventory_transactions` for returns.
- Triggers and rebuild helpers update stock valuation and dirty valuation state.
- Purchase return snapshots lock monetary return values against later purchase item changes.

### Purchase discounts/taxes/freight/extra charges

- Found order-level discount and item-level discount handling.
- No vendor/purchase tax, freight, or extra-charge field was found in active purchase schema/repo paths.
- Invoice/widget code has a purchase invoice fallback that treats purchase totals as subtotal and sets line/order discounts to zero.

### Invoice/print/template financial values

- Purchase invoice generation exists in `modules/purchase/controller.py`, `widgets/invoice_preview.py`, and `resources/templates/invoices/purchase_invoice.html`.
- `widgets/invoice_preview.py` contains a display-only purchase total fallback that does not use order/item discounts.
- Vendor history template displays statement rows and totals.

### Status calculations

- Payment status is computed in schema triggers, repository methods, purchase search SQL, purchase model display, details display, reports, and tests.
- Status values are `paid`, `unpaid`, and `partial`.

### Reports/history/export flows

- Vendor aging, financial reports, payment reports, purchase reports, and comprehensive payment reports all read or calculate vendor/purchase accounting values.
- CSV/HTML/export flows consume these report rows.

### Tests covering vendor/purchase accounting

- Strong test coverage exists for vendor advances, purchase payments, purchase returns, refunds, bank validation, vendor statement, status recalculation, and reports.
- Missing coverage remains around a single consolidated source of truth and invoice/template financial consistency.

### Other hidden or indirect accounting behavior

- `database/__init__.py` exposes unresolved purchase return count.
- `modules/sales/` references purchase behavior only indirectly in comments or mirrored payment UI patterns; no direct vendor/purchase writes found there.
- `modules/expense/` has expense CRUD/reporting but no direct vendor payable linkage found.
- Backup/restore tests and service references are generic DB handling, not vendor/purchase accounting rules.

## Detailed Reference Map

| Area | File | Class/Function | Line(s) | Behavior | Reads | Writes | Calculates | Displays | Tables/Repos | Future AccountingService Candidate | Notes |
|---|---|---|---:|---|---|---|---|---|---|---|---|
| Schema: purchase header | `database/schema.py` | `CREATE TABLE purchases` | 162 | Stores vendor, total, order discount, payment status, paid amount, applied advance. | No | Yes | No | No | `purchases`, `vendors` | `get_purchase_outstanding`, `get_purchase_payment_status` | Source-of-truth storage fields. |
| Schema: purchase items | `database/schema.py` | `CREATE TABLE purchase_items` | 232 | Stores quantity, purchase price, sale price, item discount. | No | Yes | No | No | `purchase_items` | `calculate_purchase_total` | Purchase total base data. |
| Schema: inventory ledger | `database/schema.py` | `CREATE TABLE inventory_transactions` | 317 | Stores purchase and purchase return stock movements. | No | Yes | No | No | `inventory_transactions` | `record_purchase_inventory_event`, `record_purchase_return_event` | Inventory-accounting coupling. |
| Schema: return snapshots | `database/schema.py` | `CREATE TABLE purchase_return_snapshots` | 345 | Stores immutable return valuation values. | No | Yes | Yes | No | `purchase_return_snapshots` | `preview_purchase_return_effect` | Source-of-truth for return value snapshots. |
| Schema: purchase payments | `database/schema.py` | `CREATE TABLE purchase_payments` | 585 | Stores vendor payments, method, bank, instrument, clearing state. | No | Yes | No | No | `purchase_payments`, `company_bank_accounts`, `vendor_bank_accounts` | `record_vendor_payment_event` | Cash/bank write side. |
| Schema: vendor bank accounts | `database/schema.py` | `CREATE TABLE vendor_bank_accounts` | 615 | Stores vendor destination bank accounts and active/primary flags. | No | Yes | No | No | `vendor_bank_accounts` | `validate_vendor_payment_destination` | Payment validation dependency. |
| Schema: purchase refunds | `database/schema.py` | `CREATE TABLE purchase_refunds` | 636 | Stores supplier refunds received for purchase returns. | No | Yes | No | No | `purchase_refunds`, `purchases`, `vendors` | `record_supplier_refund_event` | Cash/bank inflow on vendor side. |
| Schema: refund ownership | `database/schema.py` | `trg_purchase_refunds_ownership_ins/upd` | 668, 684 | Validates refund vendor and vendor bank account match purchase vendor. | Yes | No | No | No | `purchase_refunds`, `purchases`, `vendor_bank_accounts` | `validate_supplier_refund` | DB validation source. |
| Schema: refund active accounts | `database/schema.py` | `trg_purchase_refunds_active_accounts_ins/upd` | 700, 717 | Rejects inactive company/vendor accounts on refunds. | Yes | No | No | No | `company_bank_accounts`, `vendor_bank_accounts`, `purchase_refunds` | `validate_bank_account_active` | DB validation source. |
| Schema: vendor payment destination | `database/schema.py` | `trg_pp_vendor_account_vendor_match_ins/upd` | 748, 767 | Validates purchase payment vendor bank belongs to purchase vendor. | Yes | No | No | No | `purchase_payments`, `purchases`, `vendor_bank_accounts` | `validate_vendor_payment_destination` | DB validation source. |
| Schema: vendor payment active accounts | `database/schema.py` | `trg_pp_active_accounts_ins/upd` | 786, 803 | Rejects inactive accounts for purchase payments. | Yes | No | No | No | `purchase_payments`, `company_bank_accounts`, `vendor_bank_accounts` | `validate_bank_account_active` | DB validation source. |
| Schema: vendor advances | `database/schema.py` | `CREATE TABLE vendor_advances` | 829 | Stores vendor credit/deposit, applied credit, and return credit as signed ledger rows. | No | Yes | No | No | `vendor_advances`, `vendors`, bank tables | `record_vendor_advance_event` | Source-of-truth credit ledger. |
| Schema: vendor advance method | `database/schema.py` | `trg_vadv_card_method_ins/upd` | 860, 869 | Rejects card method for vendor advance/payment metadata. | Yes | No | No | No | `vendor_advances` | `validate_vendor_payment_method` | Hardcoded method assumption. |
| Schema: vendor advance cleared-only | `database/schema.py` | `trg_vadv_cleared_only_ins/upd` | 878, 887 | Requires vendor outgoing payment metadata to be cleared if clearing state is present. | Yes | No | No | No | `vendor_advances` | `validate_vendor_payment_state` | Hardcoded cleared-only assumption. |
| Schema: vendor advance bank ownership | `database/schema.py` | `trg_vadv_vendor_account_vendor_match_ins/upd` | 896, 909 | Validates vendor bank belongs to advance vendor. | Yes | No | No | No | `vendor_advances`, `vendor_bank_accounts` | `validate_vendor_payment_destination` | DB validation source. |
| Schema: vendor advance active accounts | `database/schema.py` | `trg_vadv_active_accounts_ins/upd` | 922, 939 | Rejects inactive company/vendor accounts for vendor advances. | Yes | No | No | No | `vendor_advances`, bank tables | `validate_bank_account_active` | DB validation source. |
| Schema: returned item guards | `database/schema.py` | `trg_purchase_items_return_delete_guard`, `trg_purchase_items_return_identity_guard` | 1078, 1093 | Blocks deleting/changing items referenced by returns. | Yes | No | No | No | `purchase_items`, `inventory_transactions` | `validate_purchase_edit_after_return` | Hidden inventory-return coupling. |
| Schema: vendor change guard | `database/schema.py` | `trg_purchases_vendor_change_guard` | 1140 | Blocks vendor change after payments, credits, returns, or refunds. | Yes | No | No | No | `purchases`, `purchase_payments`, `vendor_advances`, `inventory_transactions`, `purchase_refunds` | `validate_purchase_vendor_change` | Source-of-truth guard. |
| Schema: purchase return snapshots | `database/schema.py` | `trg_purchase_return_snapshot_insert` | 1301 | Captures purchase return valuation snapshot from return inventory transaction. | Yes | Yes | Yes | No | `inventory_transactions`, `purchase_items`, `purchase_return_snapshots` | `record_purchase_return_event` | Source-of-truth return valuation capture. |
| Schema: return snapshot immutability | `database/schema.py` | `trg_purchase_return_snapshot_update/delete_guard` | 1350, 1358 | Blocks edits/deletes to purchase return snapshots. | Yes | No | No | No | `purchase_return_snapshots` | `validate_purchase_return_snapshot` | Immutability guard. |
| Schema: return transaction immutability | `database/schema.py` | `trg_purchase_return_transaction_update_guard` | 1370 | Blocks purchase return transaction changes that would desync snapshots. | Yes | No | No | No | `inventory_transactions`, `purchase_return_snapshots` | `validate_purchase_return_event` | Hidden inventory/accounting guard. |
| Schema: paid rollup from payments | `database/schema.py` | `trg_paid_from_purchase_payments_ai/au/ad` | 2190, 2228, 2266 | Updates `purchases.paid_amount` and status from cleared purchase payments. | Yes | Yes | Yes | No | `purchase_payments`, `purchases`, `purchase_detailed_totals` | `recalculate_purchase_payment_status` | Source-of-truth candidate. |
| Schema: payment method checks | `database/schema.py` | `trg_pp_method_checks_ins/upd` | 2310, 2396 | Validates method/instrument/account requirements for purchase payments. | Yes | No | No | No | `purchase_payments`, bank tables | `validate_vendor_payment_method` | Hardcoded method rules. |
| Schema: vendor credit overdraw | `database/schema.py` | `trg_vendor_advances_no_overdraw` | 2480 | Blocks applying more vendor credit than available. | Yes | No | Yes | No | `vendor_advances` | `validate_vendor_credit_application` | Source-of-truth validation. |
| Schema: vendor credit due cap | `database/schema.py` | `trg_vendor_advances_not_exceed_remaining_due` | 2499 | Blocks applying vendor credit beyond remaining purchase due. | Yes | No | Yes | No | `vendor_advances`, `purchases`, `purchase_detailed_totals` | `validate_vendor_credit_application` | Source-of-truth validation. |
| Schema: applied advance rollup | `database/schema.py` | `trg_adv_applied_from_vendor_ai/au/ad` | 2581, 2619, 2657 | Updates `purchases.advance_payment_applied` and status from applied vendor credit. | Yes | Yes | Yes | No | `vendor_advances`, `purchases`, `purchase_detailed_totals` | `recalculate_purchase_payment_status` | Source-of-truth candidate. |
| Schema: vendor balance view | `database/schema.py` | `CREATE VIEW v_vendor_advance_balance` | 2697 | Sums signed vendor advances by vendor. | Yes | No | Yes | No | `vendor_advances` | `get_vendor_advance_balance` | Source-of-truth candidate. |
| Schema: purchase detailed totals view | `database/schema.py` | `CREATE VIEW purchase_detailed_totals` | 2754 | Calculates gross subtotal, order discount, returned value, net purchase total. | Yes | No | Yes | No | `purchases`, `purchase_items`, `purchase_return_valuations` | `get_purchase_outstanding` | Source-of-truth candidate. |
| Schema: bank ledger views | `database/schema.py` | `CREATE VIEW v_bank_ledger`, `v_bank_ledger_ext` | 3071, 3229 | Combines bank/cash ledger events including vendor disbursements/refunds/advances. | Yes | No | Yes | No | bank tables, payment/advance/refund tables | `get_bank_ledger` | Hidden bank coupling. |
| Schema: return valuation view | `database/schema.py` | `CREATE VIEW purchase_return_valuations` | 3116 | Exposes purchase return snapshot valuation rows. | Yes | No | Yes | No | `purchase_return_snapshots` | `get_purchase_return_values` | Source-of-truth candidate. |
| Schema: purchase events view | `database/schema.py` | `CREATE VIEW purchase_financial_events` | 3138 | Emits purchase and return financial events for reports. | Yes | No | Yes | No | `purchases`, `purchase_items`, returns | `get_purchase_financial_events` | Report source. |
| Schema: unresolved returns view | `database/schema.py` | `CREATE VIEW v_unresolved_purchase_returns` | 3214 | Tracks purchase returns that may need settlement follow-up. | Yes | No | Yes | No | purchase return/refund/credit data | `get_unresolved_purchase_returns` | Follow-up workflow source. |
| Vendor repo balance | `database/repositories/vendors_repo.py` | `VendorsRepo.vendor_balances` | 68 | Batch reads vendor credit balance for list hydration. | Yes | No | No | No | `vendors`, `v_vendor_advance_balance` | `get_vendor_advance_balance` | Read-side balance query. |
| Vendor advance apply | `database/repositories/vendor_advances_repo.py` | `VendorAdvancesRepo.apply_credit_to_purchase` | 45 | Prevalidates and writes negative vendor advance to apply credit to purchase. | Yes | Yes | Yes | No | `vendor_advances`, `purchases`, `purchase_detailed_totals` | `record_vendor_credit_application` | Write-side event. |
| Vendor advance grant | `database/repositories/vendor_advances_repo.py` | `VendorAdvancesRepo.grant_credit` | 114 | Validates and writes positive vendor credit/deposit/return credit with payment metadata. | Yes | Yes | No | No | `vendor_advances`, bank tables | `record_vendor_advance_event` | Write-side event. |
| Vendor balance read | `database/repositories/vendor_advances_repo.py` | `VendorAdvancesRepo.get_balance` | 245 | Reads vendor credit balance. | Yes | No | Yes | No | `v_vendor_advance_balance`, fallback `vendor_advances` | `get_vendor_advance_balance` | Source-of-truth candidate. |
| Vendor ledger read | `database/repositories/vendor_advances_repo.py` | `VendorAdvancesRepo.list_ledger` | 279 | Reads vendor advance/credit ledger rows. | Yes | No | No | No | `vendor_advances` | `get_vendor_credit_ledger` | Statement input. |
| Vendor payment metadata validation | `database/repositories/vendor_advances_repo.py` | `_validate_payment_metadata` | 428 | Validates method, bank accounts, ownership, active status, clearing state. | Yes | No | No | No | `company_bank_accounts`, `vendor_bank_accounts` | `validate_vendor_payment_metadata` | Python duplicate of DB checks. |
| Vendor credit due read | `database/repositories/vendor_advances_repo.py` | `_get_purchase_remaining_due` | 479 | Calculates purchase remaining due for credit application. | Yes | No | Yes | No | `purchases`, `purchase_detailed_totals` | `get_purchase_outstanding` | Source-of-truth candidate. |
| Purchase payment write | `database/repositories/purchase_payments_repo.py` | `PurchasePaymentsRepo.record_payment` | 15 | Records cleared vendor payment, validates banks, converts overpayment to vendor credit. | Yes | Yes | Yes | No | `purchase_payments`, `purchases`, `purchase_detailed_totals`, `vendor_advances` | `record_vendor_payment_event`, `preview_vendor_payment_effect` | High-risk write side. |
| Purchase payment state update | `database/repositories/purchase_payments_repo.py` | `update_clearing_state` | 188 | Keeps purchase payment clearing state cleared. | Yes | Yes | No | No | `purchase_payments` | `update_vendor_payment_state` | Cleared-only assumption. |
| Purchase payments list | `database/repositories/purchase_payments_repo.py` | `list_payments`, `list_payments_for_vendor` | 212, 238 | Reads vendor payment rows for purchase/vendor history. | Yes | No | No | No | `purchase_payments`, `purchases` | `get_vendor_payment_history` | Read-side query. |
| Latest payment read | `database/repositories/purchase_payments_repo.py` | `get_latest_payment_for_purchase` | 284 | Reads latest vendor payment with bank labels. | Yes | No | No | Yes | `purchase_payments`, bank tables | `get_purchase_payment_history` | Display-only query. |
| Purchase list query | `database/repositories/purchases_repo.py` | `_purchase_list_select_sql`, `list_purchases`, `search_purchases` | 58, 91, 102 | Reads gross/net totals, returned value, paid/advance, return credit, remaining due, status. | Yes | No | Yes | No | `purchases`, `purchase_detailed_totals`, `purchase_return_valuations`, `vendor_advances` | `list_purchase_summaries` | Source-of-truth candidate for list values. |
| Purchase vendor lock | `database/repositories/purchases_repo.py` | `has_vendor_locking_activity` | 165 | Checks if vendor can be changed after accounting activity. | Yes | No | No | No | `purchase_payments`, `vendor_advances`, `inventory_transactions`, `purchase_refunds` | `validate_purchase_vendor_change` | Mirrors schema guard. |
| Purchase detail snapshot | `database/repositories/purchases_repo.py` | `get_purchase_detail_snapshot` | 209 | Reads header/items/latest payment and calculated totals for UI. | Yes | No | Yes | No | purchase tables, `purchase_payments`, `vendor_advances` | `get_purchase_detail_financials` | UI read model. |
| Purchase create | `database/repositories/purchases_repo.py` | `create_purchase` | 363 | Calculates total, writes unpaid purchase header/items/inventory rows. | No | Yes | Yes | No | `purchases`, `purchase_items`, `inventory_transactions` | `record_purchase_event` | Write-side source. |
| Purchase update | `database/repositories/purchases_repo.py` | `update_purchase` | 433 | Recalculates total, validates settlement floor, rebuilds purchase inventory rows. | Yes | Yes | Yes | No | purchase tables, payments, advances, returns, refunds | `update_purchase_event` | High-risk write side. |
| Purchase return | `database/repositories/purchases_repo.py` | `record_return`, `_record_return` | 651, 679 | Validates return quantities/stock, writes return inventory, creates refund or vendor return credit. | Yes | Yes | Yes | No | `inventory_transactions`, `purchase_return_snapshots`, `purchase_refunds`, `vendor_advances` | `record_purchase_return_event`, `preview_purchase_return_effect` | High-risk source-of-truth candidate. |
| Purchase delete | `database/repositories/purchases_repo.py` | `delete_purchase` | 1059 | Deletes purchase content and inventory transactions. | Yes | Yes | No | No | `inventory_transactions`, `purchase_items`, `purchases` | `delete_purchase_event` | Accounting side effect. |
| Vendor purchase list | `database/repositories/purchases_repo.py` | `list_purchases_by_vendor` | 1066 | Reads vendor purchases with gross and net totals for statement. | Yes | No | Yes | No | `purchases`, `purchase_detailed_totals` | `get_vendor_statement` | Statement input. |
| Vendor purchase totals | `database/repositories/purchases_repo.py` | `get_purchase_totals_for_vendor` | 1110 | Sums purchase total, paid total, applied advance by vendor. | Yes | No | Yes | No | `purchases` | `get_vendor_purchase_totals` | Read-side summary. |
| Purchase return values | `database/repositories/purchases_repo.py` | `list_return_values_by_purchase`, `purchase_return_totals` | 1140, 1181 | Reads return valuation rows and totals. | Yes | No | Yes | No | `purchase_return_valuations` | `get_purchase_return_values` | Source-of-truth candidate. |
| Returnable qty | `database/repositories/purchases_repo.py` | `get_returnable_map` | 1159 | Calculates remaining returnable quantity per purchase item. | Yes | No | Yes | No | `purchase_items`, `inventory_transactions` | `get_purchase_returnable_quantities` | Inventory/accounting coupling. |
| Purchase financials | `database/repositories/purchases_repo.py` | `fetch_purchase_financials` | 1216 | Reads totals, paid, applied credit, return credit, refunds, direct payments, remaining refundable amount. | Yes | No | Yes | No | purchase tables, payments, advances, refunds | `get_purchase_financials` | Source-of-truth candidate. |
| Remaining due | `database/repositories/purchases_repo.py` | `get_remaining_due_header`, `get_purchase_remaining_due` | 1280, 1376 | Calculates remaining due from net total, paid, applied credit. | Yes | No | Yes | No | `purchases`, `purchase_detailed_totals` | `get_purchase_outstanding` | Source-of-truth candidate. |
| Header status recalculation | `database/repositories/purchases_repo.py` | `update_header_totals` | 1304 | Recomputes `paid_amount` and `payment_status` from cleared payments and applied credit. | Yes | Yes | Yes | No | `purchase_payments`, `purchases`, `purchase_detailed_totals` | `recalculate_purchase_payment_status` | Duplicates SQL triggers. |
| Open purchases | `database/repositories/purchases_repo.py` | `get_open_purchases_for_vendor` | 1349 | Reads vendor purchases with positive remaining balance. | Yes | No | Yes | No | `purchases`, `purchase_detailed_totals` | `get_vendor_open_purchases` | Used for credit allocation. |
| Vendor controller balance | `modules/vendor/controller.py` | `_hydrate_visible_balances`, `_update_details`, `_vendor_credit_balance` | 183, 223, 332 | Loads and displays vendor credit balance. | Yes | No | No | Yes | `VendorsRepo`, `VendorAdvancesRepo` | `get_vendor_advance_balance` | UI display plus fallback. |
| Vendor open purchase helpers | `modules/vendor/controller.py` | `_open_purchases_for_vendor`, `_list_open_purchases_for_vendor`, `_remaining_due_for_purchase` | 293, 295, 319 | Reads open purchases and due for credit application. | Yes | No | Yes | No | `PurchasesRepo` | `get_vendor_open_purchases` | Allocation dependency. |
| Vendor credit preview | `modules/vendor/controller.py` | `_build_grant_credit_allocation_preview` | 361 | Allocates grant credit to open purchases FIFO by date/id and leaves excess credit. | Yes | No | Yes | Yes | `PurchasesRepo`, controller helpers | `preview_vendor_advance_allocation` | Source-of-truth candidate for FIFO. |
| Vendor credit auto-apply | `modules/vendor/controller.py` | `_grant_credit_and_auto_apply` | 396 | Writes vendor credit and applies it to purchases atomically. | Yes | Yes | Yes | No | `VendorAdvancesRepo` | `record_vendor_advance_event` | Write-side orchestration. |
| Vendor advance dialog | `modules/vendor/controller.py` | `_on_apply_advance_dialog`, `_open_grant_credit_dialog` | 769, 1249 | Opens UI and records advance/credit with bank metadata. | Yes | Yes | No | Yes | `VendorAdvancesRepo`, bank repos | `record_vendor_advance_event` | UI write path. |
| Vendor statement | `modules/vendor/controller.py` | `build_vendor_statement` | 847 | Calculates opening payable/credit, statement rows, effects, totals, closing balance. | Yes | No | Yes | Yes | purchases, payments, refunds, advances | `get_vendor_statement` | Major source-of-truth candidate. |
| Vendor history UI | `modules/vendor/payment_history_view.py` | `VendorPaymentHistoryDialog` | 138, 191, 548 | Displays opening payable/credit, statement rows, and exports/prints history. | Yes | No | No | Yes | controller payload | `get_vendor_statement` | Display-only. |
| Vendor details UI | `modules/vendor/details.py` | `VendorDetails.set_credit` | 61 | Displays vendor credit/balance. | Yes | No | No | Yes | controller payload | `get_vendor_advance_balance` | Display-only. |
| Purchase controller add | `modules/purchase/controller.py` | `_handle_add_dialog_accept` | 559 | Creates purchase, optional initial payment, optional initial/auto vendor credit application. | Yes | Yes | Yes | No | `PurchasesRepo`, `PurchasePaymentsRepo`, `VendorAdvancesRepo` | `record_purchase_event` | High-risk orchestration. |
| Purchase invoice print | `modules/purchase/controller.py` | `_print_purchase_invoice`, `_generate_invoice_html_content` | 778, 842 | Builds purchase invoice context with totals, status, payments, bank labels. | Yes | No | Yes | Yes | purchase tables, payment repos, templates | `get_purchase_invoice_financials` | Display/report only. |
| Purchase edit | `modules/purchase/controller.py` | `_edit` | 1002 | Updates purchase and optionally auto-applies vendor credit after edit. | Yes | Yes | Yes | No | `PurchasesRepo`, `VendorAdvancesRepo` | `update_purchase_event` | Write-side orchestration. |
| Purchase return UI action | `modules/purchase/controller.py` | `_return` | 1125 | Opens return form, writes purchase return, recomputes header totals. | Yes | Yes | Yes | Yes | `PurchasesRepo`, bank repos | `record_purchase_return_event` | Write-side orchestration. |
| Apply vendor credit action | `modules/purchase/controller.py` | `apply_vendor_credit` | 1209 | Applies existing vendor credit to selected purchase. | Yes | Yes | Yes | Yes | `VendorAdvancesRepo`, `PurchasesRepo` | `record_vendor_credit_application` | Write-side path. |
| Purchase payment action | `modules/purchase/controller.py` | `_payment` | 1261 | Opens payment form and records purchase payment. | Yes | Yes | Yes | Yes | `PurchasePaymentsRepo`, `PurchasesRepo` | `record_vendor_payment_event` | Write-side path. |
| Purchase payment summary | `modules/purchase/controller.py` | `_latest_purchase_payment`, `_overpayment_credited`, `_refresh_payment_summary` | 477, 494, 507 | Reads latest payment and overpayment credit for details panel. | Yes | No | Yes | Yes | `purchase_payments`, `vendor_advances` | `get_purchase_payment_summary` | Display-only. |
| Purchase form vendor balance | `modules/purchase/form.py` | `_update_vendor_advance_display` | 504 | Displays vendor balance/receivable text in purchase form. | Yes | No | No | Yes | `VendorAdvancesRepo` | `get_vendor_advance_balance` | Display-only. |
| Purchase form totals | `modules/purchase/form.py` | `_recalc_row`, `_calc_subtotal`, `_refresh_totals`, `get_payload` | 1105, 1132, 1143, 1429 | Calculates line totals, subtotal, order discount, total, initial payment/credit payload. | Yes | No | Yes | Yes | UI fields | `preview_purchase_total` | Client-side pre-save calculation. |
| Initial payment validation | `modules/purchase/form.py` | `_validate_initial_payment` | 1343 | Validates payment method/account/instrument requirements for initial payment. | Yes | No | No | Yes | bank repos/UI fields | `validate_vendor_payment_metadata` | Duplicates payment form/schema. |
| Purchase payment form due | `modules/purchase/payment_form.py` | `_calculate_remaining_amount` | 248 | Reads and displays remaining payable amount. | Yes | No | Yes | Yes | `purchases`, `purchase_detailed_totals` | `get_purchase_outstanding` | Display-only. |
| Purchase payment form bank metadata | `modules/purchase/payment_form.py` | `_reload_company_accounts`, `_reload_vendor_accounts`, `_validate_payment`, `get_payload` | 283, 306, 564, 648 | Loads active bank accounts, validates payment method, emits payment payload. | Yes | No | No | Yes | bank tables/UI fields | `validate_vendor_payment_metadata` | UI validation duplicate. |
| Purchase return form valuation | `modules/purchase/return_form.py` | `_compute_return_value_factor`, `_refresh_totals`, `payload` | 379, 556, 599 | Calculates displayed return value from item discount and order discount; builds settlement payload. | Yes | No | Yes | Yes | purchase items/UI fields | `preview_purchase_return_effect` | Client-side preview. |
| Purchase return form financials | `modules/purchase/return_form.py` | settlement helpers | 794 | Uses purchase financials to decide refund/credit settlement UI. | Yes | No | Yes | Yes | `PurchasesRepo.fetch_purchase_financials` | `preview_purchase_return_effect` | Display/prevalidation. |
| Purchase details UI | `modules/purchase/details.py` | `set_data`, `set_payment_summary` | 56, 142 | Displays gross total, returned value, net, paid, credit applied, remaining, status, overpayment. | Yes | No | Yes | Yes | purchase row dict | `get_purchase_financials` | Display-only fallback math. |
| Purchase table model | `modules/purchase/model.py` | `_payment_bg`, `_fully_returned`, `data` | 22, 33, 49 | Displays payment status colors and purchase total/paid/due values. | Yes | No | Yes | Yes | purchase row dict | `get_purchase_financials` | Display-only. |
| Invoice preview widget | `widgets/invoice_preview.py` | `_prepare_invoice_data` | 96 | Reads purchase header/items/payment and computes invoice totals fallback. | Yes | No | Yes | Yes | `purchases`, `purchase_items`, `purchase_payments`, bank tables | `get_purchase_invoice_financials` | Display-only; has hardcoded discount zero fallback. |
| Purchase invoice template | `resources/templates/invoices/purchase_invoice.html` | template | 68, 140, 151, 164 | Displays purchase status, vendor, company bank details, total, paid amount, payment rows. | Yes | No | No | Yes | invoice context | `get_purchase_invoice_financials` | Display-only. |
| Vendor history template | `resources/templates/invoices/vendor_history_table.html` | template | 79, 108 | Displays vendor statement identity and totals. | Yes | No | No | Yes | statement context | `get_vendor_statement` | Display-only. |
| Reporting cutoff vendor headers | `database/repositories/reporting_repo.py` | `vendor_headers_as_of`, `_vendor_headers_as_of_rows` | 78, 93 | Calculates AP remaining due as of cutoff from purchases, returns, cleared payments, applied credits. | Yes | No | Yes | No | purchase tables, `purchase_payments`, `vendor_advances`, snapshots | `get_vendor_aging` | Report source-of-truth candidate. |
| Reporting vendor credit cutoff | `database/repositories/reporting_repo.py` | `vendor_credit_as_of_batch`, `vendor_credit_as_of` | 184, 208 | Calculates vendor credit as of date from signed advances. | Yes | No | Yes | No | `vendor_advances` | `get_vendor_advance_balance` | Report read-side query. |
| Reporting disbursements | `database/repositories/reporting_repo.py` | `purchase_disbursements_by_day` | 910 | Groups cleared vendor payments and cleared supplier refunds by cleared date. | Yes | No | Yes | No | `purchase_payments`, `purchase_refunds` | `get_vendor_cash_movements` | Cash/bank report source. |
| Purchase reports totals | `modules/reporting/purchase_reports.py` | report queries | 414, 441, 604, 687, 706, 731, 766 | Reads purchase details, financial events, returns, outstanding, payments. | Yes | No | Yes | Yes | `purchase_detailed_totals`, `purchase_financial_events`, `purchase_return_valuations`, `purchase_payments` | `get_purchase_reports` | Report/display. |
| Vendor aging reports | `modules/reporting/vendor_aging_reports.py` | aging logic | 83, 159, 358 | Calculates vendor AP buckets from total, paid, applied advances. | Yes | No | Yes | Yes | `ReportingRepo` | `get_vendor_aging` | Report/display. |
| Financial reports | `modules/reporting/financial_reports.py` | AP/cash views | 102, 115, 162, 181 | Calculates AP total and net disbursements/refunds. | Yes | No | Yes | Yes | `ReportingRepo` | `get_ap_summary`, `get_vendor_cash_movements` | Report/display. |
| Payment reports | `modules/reporting/payment_reports.py` | disbursement UI | 140, 296 | Displays vendor payment disbursements/refunds/net outflow. | Yes | No | Yes | Yes | `ReportingRepo` | `get_vendor_cash_movements` | Report/display. |
| Comprehensive payments | `modules/reporting/comprehensive_payments_reports.py` | payment queries | 162, 183, 237, 306 | Reads purchase payments and purchase refunds alongside sale payments. | Yes | No | Yes | Yes | `purchase_payments`, `purchase_refunds` | `get_payment_activity` | Cross-module report. |
| Inventory transactions UI | `modules/inventory/model.py`, `modules/inventory/transactions.py` | transaction display/filter | 36, 221 | Displays purchase and purchase return inventory transactions. | Yes | No | No | Yes | `inventory_transactions`, `ReportingRepo` | `get_inventory_accounting_events` | Inventory-related display. |
| Stock valuation UI | `modules/inventory/stock_valuation.py` | valuation display | 155 | Displays valuation history affected by purchase and return inventory events. | Yes | No | Yes | Yes | `stock_valuation_history` | `get_inventory_valuation` | Indirect accounting display. |
| Expense module | `modules/expense/*`, `database/repositories/expenses_repo.py` | expense CRUD/reporting | various | Expense amounts exist but no direct vendor payable/purchase link found. | Yes | Yes | No | Yes | `expenses`, `expense_categories` | None found | Important no-link finding. |
| Sales module indirect | `modules/sales/*` | comments/mirrored UI | various | Mentions purchase side as mirrored behavior; no direct vendor/purchase accounting write found. | No | No | No | No | sale tables | None found | Indirect only. |
| Backup/restore | `modules/backup_restore/*` | service/tests | various | Generic DB backup/restore/purge checks. No vendor/purchase accounting rule found. | Yes | Yes | No | No | whole DB | None found | Indirect artifact handling only. |

## Source-of-Truth Candidates

- `database/schema.py:162` `purchases` fields: `total_amount`, `order_discount`, `payment_status`, `paid_amount`, `advance_payment_applied`.
- `database/schema.py:232` `purchase_items` fields: purchase price and item discount.
- `database/schema.py:585` `purchase_payments`.
- `database/schema.py:636` `purchase_refunds`.
- `database/schema.py:829` `vendor_advances`.
- `database/schema.py:1301` purchase return snapshot trigger.
- `database/schema.py:2190`, `2228`, `2266` purchase paid/status triggers.
- `database/schema.py:2581`, `2619`, `2657` vendor applied advance/status triggers.
- `database/schema.py:2697` `v_vendor_advance_balance`.
- `database/schema.py:2754` `purchase_detailed_totals`.
- `database/schema.py:3116` `purchase_return_valuations`.
- `database/schema.py:3138` `purchase_financial_events`.
- `database/repositories/vendor_advances_repo.py:45` credit application.
- `database/repositories/vendor_advances_repo.py:114` credit grant.
- `database/repositories/vendor_advances_repo.py:245` vendor balance.
- `database/repositories/purchase_payments_repo.py:15` payment recording and overpayment-to-credit.
- `database/repositories/purchases_repo.py:363` purchase creation.
- `database/repositories/purchases_repo.py:433` purchase update and settlement floor.
- `database/repositories/purchases_repo.py:679` purchase return/refund/credit settlement.
- `database/repositories/purchases_repo.py:1216` purchase financials.
- `database/repositories/purchases_repo.py:1304` payment status recalculation.
- `modules/vendor/controller.py:361` FIFO-style grant-credit allocation preview.
- `modules/vendor/controller.py:847` vendor statement calculation.

## Display-Only / Derived References

- `modules/vendor/details.py:61` displays vendor credit.
- `modules/vendor/payment_history_view.py:138` displays/prints/exports vendor statement payload.
- `modules/purchase/details.py:56` displays totals, paid, applied credit, remaining, status, overpayment.
- `modules/purchase/model.py:22` displays purchase payment status colors and purchase totals.
- `modules/purchase/form.py:504` displays vendor balance in purchase form.
- `modules/purchase/payment_form.py:248` displays remaining payable.
- `modules/purchase/return_form.py:556` displays return value preview.
- `modules/purchase/controller.py:778` and `842` generate purchase invoice context.
- `widgets/invoice_preview.py:96` generates invoice preview data.
- `resources/templates/invoices/purchase_invoice.html:68` displays purchase invoice financial fields.
- `resources/templates/invoices/vendor_history_table.html:79` displays vendor statement fields.
- `modules/reporting/*` display report rows calculated by direct SQL or `ReportingRepo`.

## Write-Side Accounting Events

- Purchase creation:
  - `database/repositories/purchases_repo.py:363`
  - Writes `purchases`, `purchase_items`, `inventory_transactions`.
  - May be called from `modules/purchase/controller.py:559`.
- Purchase update:
  - `database/repositories/purchases_repo.py:433`
  - Updates purchase header/items, rebuilds purchase inventory rows, recalculates header totals.
- Purchase delete:
  - `database/repositories/purchases_repo.py:1059`
  - Deletes purchase inventory rows, items, and header.
- Purchase payment:
  - `database/repositories/purchase_payments_repo.py:15`
  - Writes `purchase_payments`, audit log, possible `vendor_advances` overpayment credit.
  - UI path `modules/purchase/controller.py:1261`.
- Initial purchase payment:
  - `modules/purchase/controller.py:559`
  - Calls `PurchasePaymentsRepo.record_payment()`.
- Vendor advance/deposit/credit:
  - `database/repositories/vendor_advances_repo.py:114`
  - UI paths `modules/vendor/controller.py:769`, `1249`, `396`.
- Vendor credit application:
  - `database/repositories/vendor_advances_repo.py:45`
  - UI paths `modules/purchase/controller.py:1209`, `modules/vendor/controller.py:396`.
- Purchase return:
  - `database/repositories/purchases_repo.py:651`, `679`
  - Writes `inventory_transactions`, audit logs, possible `purchase_refunds` or `vendor_advances.return_credit`.
  - UI path `modules/purchase/controller.py:1125`.
- Supplier refund:
  - `database/repositories/purchases_repo.py:992`
  - Writes `purchase_refunds`.
- Bank/cash movement:
  - `purchase_payments`, `purchase_refunds`, and `vendor_advances` carry bank/cash metadata.
  - `database/schema.py:3071`, `3229` expose bank ledger views.
- Payment status update:
  - SQL triggers at `database/schema.py:2190`, `2228`, `2266`, `2581`, `2619`, `2657`.
  - Python method at `database/repositories/purchases_repo.py:1304`.

## Read-Side Accounting Queries

- Vendor balance:
  - `database/schema.py:2697`
  - `database/repositories/vendor_advances_repo.py:245`
  - `database/repositories/vendors_repo.py:68`
  - `modules/vendor/controller.py:183`, `223`, `332`
  - `modules/purchase/form.py:504`
- Vendor ledger/history/statement:
  - `database/repositories/vendor_advances_repo.py:279`
  - `database/repositories/purchase_payments_repo.py:238`
  - `modules/vendor/controller.py:847`
- Purchase outstanding:
  - `database/schema.py:2754`
  - `database/repositories/purchases_repo.py:1280`, `1376`
  - `modules/purchase/payment_form.py:248`
- Paid/unpaid/partial status:
  - `database/schema.py:2190`, `2228`, `2266`, `2581`, `2619`, `2657`
  - `database/repositories/purchases_repo.py:102`, `1304`
  - `modules/purchase/model.py:22`
- Advance balance:
  - `database/schema.py:2697`
  - `database/repositories/vendor_advances_repo.py:245`
- Credit balance:
  - Same as advance balance; currently vendor credit and advance share `vendor_advances`.
- Refund totals:
  - `database/repositories/purchases_repo.py:1216`
  - `database/repositories/reporting_repo.py:910`
  - `modules/reporting/payment_reports.py:296`
- Bank/cash balance impact:
  - `database/schema.py:3071`, `3229`
  - `database/repositories/reporting_repo.py:910`
- Inventory cost/valuation impact:
  - `database/schema.py:1301`, `1511`, `1873`, `1891`, `1904`, `1917`
  - `modules/inventory/stock_valuation.py`

## Test Coverage Found

- `tests/vendor/test_vendor_advance.py`
  - Covers vendor credit application, cross-vendor rejection, metadata persistence, temp bank metadata, FIFO preview, auto-apply atomicity, rollback.
  - Gap: consolidated `AccountingService` behavior not covered yet.
- `tests/vendor/test_vendor_statement.py`
  - Covers gross/net purchase listing after returns, statement equation, settlement row effects, metadata, opening payable, print preview.
  - Gap: statement source-of-truth split across controller/repositories remains.
- `tests/vendor/test_vendor_list_caching.py`
  - Covers batched vendor balance hydration and cached detail balance.
  - Gap: no central balance API.
- `tests/vendor/test_vendor_bank_accounts.py`
  - Covers vendor bank active/primary behavior.
  - Gap: not directly tied to all payment/refund flows.
- `tests/vendor/test_purchase_payments.py`
  - Covers purchase payment repository behavior.
  - Gap: inspect in consolidation phase for exact status expectations.
- `tests/purchase/test_purchase_vendor_payments_cleared_only.py`
  - Covers cleared-only purchase payments and vendor advances, method metadata, schema enforcement.
  - Gap: no pending/bounced vendor payment lifecycle because current behavior rejects it.
- `tests/purchase/test_purchase_bank_account_active_validation.py`
  - Covers active company/vendor account checks for purchase payments and vendor advances.
  - Gap: supplier refund active-account matrix is less broad.
- `tests/purchase/test_purchase_payment_negative_due_credit.py`
  - Covers overpayment credit conversion with negative/positive due.
  - Gap: no central preview method.
- `tests/purchase/test_purchase_payment_status_recalculation.py`
  - Covers status recomputation after payment, credit, deletion, and return.
  - Gap: DB trigger vs repo method ownership unclear.
- `tests/purchase/test_purchase_list_net_return_totals.py`
  - Covers list rows after returns, net totals, due, model display, search snapshot.
  - Gap: no service read-model contract.
- `tests/purchase/test_purchase_return.py`
  - Covers purchase return basics.
  - Gap: settlement edge cases spread into other tests.
- `tests/purchase/test_purchase_return_order_discount_allocation.py`
  - Covers order discount allocation for returns.
  - Gap: no service-level return valuation contract.
- `tests/purchase/test_purchase_return_settlement_excess.py`
  - Covers excess funded return settlement, sequential returns, advance reinstatement.
  - Gap: high-risk logic needs characterization before move.
- `tests/purchase/test_purchase_return_snapshots.py`
  - Covers return snapshot behavior.
  - Gap: migration/consolidation must preserve immutability assumptions.
- `tests/purchase/test_purchase_refund_now.py`
  - Covers refund now, cash cap, metadata, prior refunds/credit notes, rollback, statement effects.
  - Gap: no dedicated supplier refund service API.
- `tests/purchase/test_purchase_vendor_change_guard.py`
  - Covers purchase vendor lock after payments, credits, returns, refunds.
  - Gap: service validation not present.
- `tests/purchase/test_purchase_edit_settlement_guard.py`
  - Covers edit rejection below settled amount.
  - Gap: service contract missing.
- `tests/purchase/test_purchase_controller.py`
  - Covers auto-apply vendor credit and purchase invoice render mapping.
  - Gap: controller still owns orchestration choices.
- `tests/purchase/test_purchase_form.py`
  - Covers vendor balance display, purchase totals, initial payment UI.
  - Gap: display may diverge from repo totals.
- `tests/purchase/test_purchase_validation_rules.py`
  - Covers strict numeric parsing and price rules.
  - Gap: not accounting-service-specific.
- `tests/reporting/test_vendor_aging_cutoff.py`
  - Covers vendor aging cutoff ignoring later payments/returns/credits.
  - Gap: report and accounting source-of-truth separate.
- `tests/reporting/test_purchase_reports_net_totals.py`
  - Covers reports use net total after returns.
  - Gap: report SQL duplicates source calculations.
- `tests/reporting/test_purchase_reports_financial_events.py`
  - Covers purchase financial event reports.
  - Gap: financial event ownership unclear.
- `tests/reporting/test_purchase_disbursements_refunds.py`
  - Covers disbursement/refund net outflow.
  - Gap: bank ledger service missing.
- `tests/reporting/test_payment_reports_vendor_refunds.py`
  - Covers payment reports with vendor refunds.
  - Gap: report-specific logic still duplicates.
- `tests/reporting/test_purchase_reports_quantity_base.py`
  - Covers return quantity/value reporting.
  - Gap: no central return valuation read API.
- `tests/inventory/test_valuation_dirty_rebuild.py`
  - Covers purchase price change valuation rebuild effects.
  - Gap: inventory valuation service integration needed later.
- `tests/inventory/test_inventory_txn_seq_ordering.py`
  - Covers transaction sequence ordering for purchase-related inventory events.
  - Gap: service move must preserve ordering.

## Missing Characterization Tests Recommended Later

### Vendor balance

- Characterize `v_vendor_advance_balance` vs `VendorAdvancesRepo.get_balance()` for deposits, applied credit, return credit, and date cutoffs.
- Characterize vendor list/details balance display after purchase payment overpayment and return credit.

### Purchase outstanding

- Characterize remaining due for gross purchase, order discount, item discount, return, cleared payment, applied vendor credit, refund, and return credit.
- Characterize `purchase_detailed_totals` against repository `get_remaining_due_header()`.

### Vendor payments

- Characterize overpayment conversion to vendor credit and audit log side effect.
- Characterize cleared-only assumption across repo and direct SQL triggers.

### Vendor advances

- Characterize manual deposit, payment-metadata deposit, temp vendor bank metadata, and return credit in one ledger sequence.
- Characterize rejection for inactive company/vendor bank accounts in repo and direct SQL.

### Advance allocation

- Characterize FIFO allocation order: purchase date, then purchase id.
- Characterize excess credit not applied to open purchases.
- Characterize rollback if one application fails after credit grant.

### Purchase returns

- Characterize return valuation with item discount and order discount.
- Characterize multiple partial returns and snapshot immutability.
- Characterize return with stock validation and dirty valuation rebuild.

### Supplier refunds

- Characterize refund now vs credit note with prior refund and prior return credit.
- Characterize refund metadata and bank ledger/report effect.

### Bank movement

- Characterize `v_bank_ledger` and `v_bank_ledger_ext` rows for purchase payment, vendor advance, and purchase refund.
- Characterize reporting net disbursement = gross vendor payments minus supplier refunds.

### Inventory impact

- Characterize purchase create/update/delete inventory rows.
- Characterize purchase return inventory rows and valuation snapshots.

### Status calculations

- Characterize trigger and repository recomputation agreement for paid/unpaid/partial.
- Characterize status after deleting payments or applied credit.

### Invoice/report output

- Characterize purchase invoice totals with item discount, order discount, returned value, paid amount, and payments table.
- Characterize vendor statement opening balance and closing balance with refunds/credits.

## Consolidation Candidates for Later

- `AccountingService.get_vendor_balance(vendor_id)`
- `AccountingService.get_purchase_outstanding(purchase_id)`
- `AccountingService.get_vendor_advance_balance(vendor_id)`
- `AccountingService.get_vendor_statement(vendor_id, date_range=None)`
- `AccountingService.get_purchase_payment_status(purchase_id)`
- `AccountingService.get_purchase_financials(purchase_id)`
- `AccountingService.get_purchase_return_values(purchase_id)`
- `AccountingService.get_vendor_open_purchases(vendor_id)`
- `AccountingService.preview_vendor_payment_effect(...)`
- `AccountingService.preview_vendor_advance_allocation(...)`
- `AccountingService.preview_purchase_return_effect(...)`
- `AccountingService.validate_vendor_payment_metadata(...)`
- `AccountingService.validate_purchase_vendor_change(purchase_id, vendor_id)`
- `AccountingService.record_vendor_payment_event(...)`
- `AccountingService.record_vendor_advance_event(...)`
- `AccountingService.record_vendor_credit_application(...)`
- `AccountingService.record_purchase_event(...)`
- `AccountingService.update_purchase_event(...)`
- `AccountingService.record_purchase_return_event(...)`
- `AccountingService.record_supplier_refund_event(...)`
- `AccountingService.recalculate_purchase_payment_status(purchase_id)`
- `AccountingService.get_vendor_cash_movements(date_range=None)`
- `AccountingService.get_bank_ledger(date_range=None, account_id=None)`

## Risks / Unknowns

- Payment status is owned by both SQL triggers and `PurchasesRepo.update_header_totals()`.
- Purchase remaining due is recalculated in SQL views, repositories, controllers, forms, details widgets, and reports.
- Vendor statement logic lives in `modules/vendor/controller.py`, not a repository/service.
- Vendor credit allocation FIFO is controller-owned.
- Purchase return settlement mixes inventory validation, return valuation, payment/refund logic, and vendor credit reinstatement.
- `widgets/invoice_preview.py` has hardcoded purchase invoice discount values of zero.
- Purchase refunds are cleared-only in schema.
- Vendor purchase payments and advances are currently cleared-only; pending/bounced assumptions are reject-only.
- Bank ledger views need separate characterization before being treated as authoritative.
- No purchase tax/freight/extra-charge fields were found in active code paths, despite keyword search.
- Expense module has no direct vendor payable link found, but future accounting migration may add one.

## Files Inspected With No Relevant Accounting References

- `modules/expense/view.py`
- `modules/expense/form.py`
- `modules/expense/model.py`
- `modules/expense/controller.py`
- `modules/expense/category_dialog.py`
- `database/repositories/expenses_repo.py`
- `modules/payments/controller.py`
- `modules/payments/__init__.py`
- `utils/auth.py`
- `utils/combo_search.py`
- `utils/helpers.py`
- `utils/loggers.py`
- `utils/product_lookup.py`
- `utils/ui_helpers.py`
- `utils/validators.py`
- `utils/invoice_preview.py`
- `widgets/payment_status_widget.py`
- `widgets/allocation_widget.py`
- `widgets/report_preview.py`
- `widgets/searchable_combo.py`
- `widgets/table_view.py`
- `resources/templates/reports/expense_summary.html`
- `resources/templates/reports/inventory_valuation.html`
- `modules/backup_restore/service.py`
- `modules/backup_restore/controller.py`
- `modules/backup_restore/sqlite_ops.py`
- `modules/sales/controller.py` for direct vendor/purchase accounting writes.
- `modules/sales/form.py` for direct vendor/purchase accounting writes.
- `modules/sales/model.py` for direct vendor/purchase accounting writes.
- `modules/sales/details.py` for direct vendor/purchase accounting writes.

## Final Confirmation

- No behavior was changed.
- No code was refactored.
- No accounting rules were corrected.
- No database migrations or schemas were changed.
- No UI behavior was changed.
- This document is only a reference map for a future consolidation task.
