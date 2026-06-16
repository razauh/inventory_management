# UI Performance Audit

Date: 2026-06-16

## Executive summary

Main lag source is not one bug. Main lag comes from same pattern in many modules:

- full result sets loaded into widgets at once
- expensive `resizeColumnsToContents()` on large tables
- repeated detail queries on every selection/filter change
- synchronous report refresh on UI thread
- some screens reconnect selection signals on every reload
- some history screens use `QTableWidget` row-by-row item creation for all rows

Worst screens for large record counts are:

1. Sales main screen
2. Purchases main screen
3. Reporting module, especially Sales, Purchases, Payments
4. Customers main screen
5. Products main screen
6. Expenses main screen

Inventory transaction screens are more bounded than others because they cap rows. Vendor main screen is lighter than Sales/Purchases, but still has avoidable full-table and detail-panel work.

## Modules/screens audited

- `main.py` lazy-loaded shell
- Dashboard
- Products
- Inventory
  - Stock Valuation
  - Transactions
  - Adjustments
- Vendors
  - main list/detail/accounts
  - vendor history dialog
- Purchases
- Customers
  - main list/detail
  - customer history dialog
- Sales
- Expenses
- Reporting
  - Vendor Aging
  - Customer Aging
  - Inventory reports
  - Expense reports
  - Financial reports
  - Sales reports
  - Purchase reports
  - Payment reports
  - Enhanced payment reports
  - Comprehensive payment reports

## Overall patterns found

### 1. Full-table loading

Many main screens call repo `list_*()` methods and bind the entire result to the table model:

- Products: `database/repositories/products_repo.py:58-72`
- Vendors: `database/repositories/vendors_repo.py:32-36`
- Customers: `database/repositories/customers_repo.py:41-50`
- Purchases: `database/repositories/purchases_repo.py:56-82`
- Sales: `database/repositories/sales_repo.py:119-177`

This means UI cost grows linearly with row count before the user can interact.

### 2. Expensive auto-sizing

Many heavy screens call `resizeColumnsToContents()` immediately after loading or refreshing:

- Products: `modules/product/controller.py:260-268`
- Vendors: `modules/vendor/controller.py:72-79`, `593-606`
- Customers: `modules/customer/controller.py:76-85`
- Purchases: `modules/purchase/controller.py:121-128`
- Sales: `modules/sales/controller.py:561-566`
- Expenses: `modules/expense/controller.py:160-165`
- Vendor history: `modules/vendor/payment_history_view.py:218-247`
- Customer history: `modules/customer/payment_history_view.py:473-507`

Qt must measure every visible cell to compute best widths. With many rows, this becomes a major repaint/layout cost.

### 3. Detail-panel query storms

Several screens run more SQL when the selected row changes, and selection changes also happen during reload/filter flows:

- Products detail and summary: `modules/product/controller.py:313-360`
- Customers details enrichment: `modules/customer/controller.py:150-199`
- Vendors details/accounts refresh: `modules/vendor/controller.py:101-160`, `593-633`
- Purchases details/items/payment summary: `modules/purchase/controller.py:261-369`
- Sales details/items/payments/credit/financials: `modules/sales/controller.py:640-756`

This makes one user action trigger multiple DB reads and multiple widget refreshes.

### 4. Rebuild model on every filter action

- Customers rebuild full model on every debounced search: `modules/customer/controller.py:102-116`
- Expenses rebuild full table and totals on every filter signal: `modules/expense/controller.py:57-65`, `101-195`
- Sales reload entire list on every keystroke: `modules/sales/controller.py:233-235`, `490-575`
- Purchases scan cached full list in Python on every search: `modules/purchase/controller.py:188-243`

### 5. Event/signal storms

- Customers connect `selectionChanged` on every `_build_model()` and never disconnect old connections: `modules/customer/controller.py:83-85`
- Sales connect `selectionChanged` on every `_build_model()` and never disconnect old connections: `modules/sales/controller.py:564-566`

If old selection models survive long enough during repeated `setModel()` cycles, this can multiply detail refresh work and make typing/searching feel progressively worse.

### 6. Reporting tab work is synchronous and eager

- Reporting controller instantiates nearly every report tab up front, including extra payment sub-tabs: `modules/reporting/controller.py:84-203`
- It also refreshes the current report immediately: `modules/reporting/controller.py:221-255`
- Sales report refresh loads many datasets in one call: `modules/reporting/sales_reports.py:403-470`
- Purchase report refresh does the same with many direct SQL blocks: `modules/reporting/purchase_reports.py:356-455`
- Enhanced payment reports merge three payment tables into one in memory: `modules/reporting/enhanced_payment_reports.py:294-374`

This is likely a major reason the Reporting module feels heavy before the user even drills into one table.

## Prioritized findings

### 1. Sales main screen reloads full list on every keystroke and re-runs many detail queries

- Severity: Critical
- Module: Sales
- Files:
  - `modules/sales/controller.py`
  - `database/repositories/sales_repo.py`
  - `database/repositories/sale_payments_repo.py`
- Class/methods:
  - `SalesController._on_search_changed`
  - `SalesController._build_model`
  - `SalesController._sync_details`
  - `SalesRepo.search_sales`
  - `SalePaymentsRepo._connect`
- Evidence:
  - Search text change calls `_reload()` directly: `modules/sales/controller.py:233-235`
  - `_build_model()` re-queries rows and rebinds the table each reload: `modules/sales/controller.py:490-566`
  - Table columns are resized after every load: `modules/sales/controller.py:561-562`
  - Selection signal is reconnected each rebuild: `modules/sales/controller.py:564-566`
  - `_sync_details()` loads items, return totals, receivable position, payments, customer credit, financial totals: `modules/sales/controller.py:656-756`
  - Payments repo opens a fresh SQLite connection from disk path: `database/repositories/sale_payments_repo.py:67-76`
- What code is doing:
  - Typing in search rebuilds the whole sales/quotation list.
  - Selecting a row repopulates items, payment data, credit data, and detail widgets.
  - Payment fetch path creates another DB connection instead of reusing shared one.
- Why it causes lag:
  - Large sales tables get fully rebound and remeasured on each keypress.
  - One selection causes several independent DB reads and multiple table repaints.
  - Extra SQLite connection setup adds overhead in hot selection path.
- Trigger:
  - Opening Sales
  - Typing in search
  - Switching Sales/Quotations mode
  - Clicking different rows
- Recommended fix direction:
  - Debounce search and avoid full `_reload()` for each keystroke.
  - Keep one model instance when possible; update rows in place.
  - Batch detail data in one query or one repo call per selected sale.
  - Reuse shared DB connection for payment/credit lookups.
  - Avoid auto-resize on large result sets.

### 2. Purchases main screen loads all rows, filters in Python, then runs multiple detail queries per selection

- Severity: Critical
- Module: Purchases
- Files:
  - `modules/purchase/controller.py`
  - `database/repositories/purchases_repo.py`
- Class/methods:
  - `PurchaseController._build_model`
  - `PurchaseController._perform_search`
  - `PurchaseController._sync_details`
  - `PurchasesRepo.list_purchases`
- Evidence:
  - Full list load: `modules/purchase/controller.py:113-128`
  - Full list cached into `_original_rows`: `modules/purchase/controller.py:114-116`
  - Search scans `_original_rows` in Python: `modules/purchase/controller.py:188-243`
  - Selection refresh hits return totals, financials, items, latest payment, overpayment summary: `modules/purchase/controller.py:261-369`
  - `list_purchases()` joins totals and returns every row ordered descending: `database/repositories/purchases_repo.py:56-82`
- What code is doing:
  - Loads every purchase row once.
  - Keeps them in memory and does substring scans in Python for search.
  - When selection changes, pulls extra detail datasets and repaints items/details panels.
- Why it causes lag:
  - In-memory filtering cost grows with record count.
  - Large tables are still fully created and auto-sized first.
  - Selection work scales with repeated row navigation.
- Trigger:
  - Opening Purchases
  - Typing search
  - Switching search radio buttons
  - Clicking rows
- Recommended fix direction:
  - Move filtering to SQL or paged fetches.
  - Avoid loading all purchase rows before search.
  - Batch detail payload for selected purchase.
  - Skip content-based auto-resize for large tables.

### 3. Reporting module eagerly constructs almost every report tab and payment sub-tab at open time

- Severity: Critical
- Module: Reporting
- Files:
  - `modules/reporting/controller.py`
  - `modules/reporting/sales_reports.py`
  - `modules/reporting/purchase_reports.py`
  - `modules/reporting/enhanced_payment_reports.py`
- Class/methods:
  - `ReportingController.__init__`
  - `SalesReportsTab.refresh`
  - `PurchaseReportsTab.refresh`
  - `EnhancedPaymentReportsTab.refresh`
- Evidence:
  - Report controller imports/builds Vendor Aging, Customer Aging, Inventory, Expenses, Financials, Sales, Purchases, Payment Summary, Enhanced Payments, Comprehensive Payments immediately: `modules/reporting/controller.py:84-203`
  - Current widget refresh is invoked at module creation: `modules/reporting/controller.py:221-255`
  - Sales report refresh loads many datasets inside one call: `modules/reporting/sales_reports.py:403-470`
  - Purchase report refresh runs many direct SQL sections inside one call: `modules/reporting/purchase_reports.py:356-455`
  - Enhanced payments refresh scans collections, disbursements, refunds into one `all_rows` list, then derives more views: `modules/reporting/enhanced_payment_reports.py:294-374`
- What code is doing:
  - Builds many heavy tabs before the user opens them.
  - Payment area creates several nested reporting tabs up front.
  - Each refresh loads large result sets on the UI thread.
- Why it causes lag:
  - Reporting open cost includes work for tabs the user may never visit.
  - Heavy SQL and list building block the main thread.
  - Each report then still resizes columns and binds full models.
- Trigger:
  - Opening Reporting
  - Switching report tabs
  - Changing date filters
- Recommended fix direction:
  - Lazy-create report tabs on first open.
  - Refresh only active sub-tab, not all child tabs eagerly.
  - Move report generation off UI thread or stream/paginate.
  - Keep `maybe_resize_columns()` and row caps, but avoid loading unused datasets.

### 4. Customers screen rebuilds whole model for each search and reconnects selection every time

- Severity: High
- Module: Customers
- Files:
  - `modules/customer/controller.py`
  - `database/repositories/customers_repo.py`
- Class/methods:
  - `CustomerController._build_model`
  - `CustomerController._apply_filter`
  - `CustomerController._details_enrichment`
  - `CustomersRepo.list_customers`
  - `CustomersRepo.search`
- Evidence:
  - `_build_model()` replaces model, resizes columns, then reconnects selection each time: `modules/customer/controller.py:71-85`
  - `_apply_filter()` reruns search/list, rebuilds model, selects row, refreshes details: `modules/customer/controller.py:106-116`
  - `_details_enrichment()` issues separate queries for balance, sales summary, last sale, last payment, last advance: `modules/customer/controller.py:150-199`
  - Base list/search return full result sets: `database/repositories/customers_repo.py:41-74`
- What code is doing:
  - Search rebuilds the entire customer table.
  - Each selected row fetches multiple summary values.
  - SelectionChanged is connected again on each model rebuild.
- Why it causes lag:
  - Search cost grows with customer count.
  - Repeated signal binding can create duplicate detail refresh behavior.
  - Detail sidebar adds extra SQL per selection.
- Trigger:
  - Opening Customers
  - Typing search
  - Clicking rows
- Recommended fix direction:
  - Keep one model/proxy and update filter without recreating table model.
  - Disconnect or reuse selection wiring safely.
  - Collapse detail enrichment into one SQL query or one repo method.

### 5. Products screen has N+1 summary queries plus per-selection detail queries

- Severity: High
- Module: Products
- Files:
  - `modules/product/controller.py`
  - `database/repositories/products_repo.py`
- Class/methods:
  - `ProductController._build_model`
  - `ProductController._update_summary`
  - `ProductController._update_selected_details`
  - `ProductsRepo.list_products`
- Evidence:
  - Full list loaded and auto-sized: `modules/product/controller.py:252-269`
  - `_update_summary()` loops all products and calls `on_hand_base()` and `latest_prices_base()` per product: `modules/product/controller.py:313-337`
  - `_update_selected_details()` fetches `get()`, `product_uoms()`, `latest_prices_base()` for selected row: `modules/product/controller.py:339-360`
  - `list_products()` itself uses correlated subqueries for UOM labels: `database/repositories/products_repo.py:58-72`
- What code is doing:
  - Every reload computes summary by walking all rows and firing extra repo queries for each product.
  - Detail panel queries more data again for the selected product.
- Why it causes lag:
  - Summary path is classic N+1 query behavior.
  - Product count growth directly multiplies DB round-trips.
  - Auto-sizing makes the initial list bind more expensive.
- Trigger:
  - Opening Products
  - Reload after create/edit/import
  - Typing search
  - Changing selection
- Recommended fix direction:
  - Precompute summary fields in batch SQL.
  - Cache per-product metrics during list fetch.
  - Do not resize all columns for large lists.

### 6. Expenses screen reruns list query and totals query on every filter control change

- Severity: High
- Module: Expenses
- Files:
  - `modules/expense/controller.py`
- Class/methods:
  - `ExpenseController.__init__`
  - `ExpenseController._reload`
  - `ExpenseController._refresh_totals`
- Evidence:
  - Search, date, category, date range, and amount range all call `_reload()` directly: `modules/expense/controller.py:56-65`
  - `_reload()` rebuilds model, sets it again, resizes columns: `modules/expense/controller.py:101-163`
  - `_refresh_totals()` runs another aggregate query after each reload: `modules/expense/controller.py:175-210`
- What code is doing:
  - One filter change triggers both detail list query and totals aggregation query.
  - Table model is recreated every time.
- Why it causes lag:
  - High-frequency UI signals become synchronous DB work.
  - Typing in search can feel slow because every character does a full refresh.
- Trigger:
  - Typing search
  - Moving date or amount filters
  - Changing category
- Recommended fix direction:
  - Debounce filter inputs.
  - Keep one model instance.
  - Separate fast row filtering from slower totals aggregation.

### 7. Dashboard initial screen does many sequential aggregate queries on UI thread

- Severity: Medium
- Module: Dashboard
- Files:
  - `modules/dashboard/controller.py`
- Class/methods:
  - `DashboardController.refresh`
- Evidence:
  - Refresh runs total sales, COGS, expenses, receipts, vendor payments, open receivables, open payables, low stock count, payment breakdowns, top products, quotations expiring in sequence: `modules/dashboard/controller.py:115-178`
- What code is doing:
  - On startup and period change, dashboard pulls many independent aggregates synchronously.
- Why it causes lag:
  - Even without huge visible grids, many aggregate queries can stall first paint and period switches.
- Trigger:
  - Opening app
  - Changing dashboard period
- Recommended fix direction:
  - Combine independent aggregates where practical.
  - Refresh cards asynchronously.
  - Defer noncritical widgets until after first paint.

### 8. Vendor main screen still does full list load plus account-table reload on each selection

- Severity: Medium
- Module: Vendors
- Files:
  - `modules/vendor/controller.py`
  - `database/repositories/vendors_repo.py`
- Class/methods:
  - `VendorController._build_model`
  - `VendorController._update_details`
  - `VendorController._reload_accounts`
  - `VendorsRepo.list_vendors`
- Evidence:
  - Full vendor list load and auto-size: `modules/vendor/controller.py:65-79`, `database/repositories/vendors_repo.py:32-36`
  - Details use `repo.get()` and advance balance lookup on selection: `modules/vendor/controller.py:101-160`
  - Accounts table reloads and resizes on each vendor selection: `modules/vendor/controller.py:593-633`
- What code is doing:
  - Left list selection repopulates right details and bank accounts.
- Why it causes lag:
  - With many vendors and many bank accounts, selection becomes a mini refresh.
  - Column auto-sizing adds extra layout cost.
- Trigger:
  - Opening Vendors
  - Typing search
  - Clicking rows
- Recommended fix direction:
  - Batch vendor detail/account counts into list query if needed.
  - Delay account-table reload until details panel is visible or selected row settles.
  - Avoid full content-based resize for large account sets.

### 9. Customer history dialog uses `QTableWidget` and populates every cell eagerly

- Severity: Medium
- Module: Customers / Payments history
- Files:
  - `modules/customer/payment_history_view.py`
- Class/methods:
  - `_TablePage._build`
  - `_TablePage._populate`
- Evidence:
  - Dialog uses `QTableWidget`: `modules/customer/payment_history_view.py:445-476`
  - It sets row count for all rows, creates `QTableWidgetItem` per cell, then uses `ResizeToContents`: `modules/customer/payment_history_view.py:485-507`
- What code is doing:
  - Builds the entire history grid eagerly from `timeline`.
- Why it causes lag:
  - `QTableWidget` item-per-cell allocation is expensive for large ledgers.
  - `ResizeToContents` forces extra measurement pass over all content.
- Trigger:
  - Opening customer history for customers with long payment/sales timelines
- Recommended fix direction:
  - Use model/view (`QAbstractTableModel` + `QTableView`) instead of `QTableWidget`.
  - Paginate or lazy-load history rows.

### 10. Vendor history dialog loads whole transaction tables and auto-resizes them immediately

- Severity: Medium
- Module: Vendors / Payments history
- Files:
  - `modules/vendor/payment_history_view.py`
- Class/methods:
  - `_VendorHistoryDialog.__init__`
  - `_VendorHistoryDialog._build_tx_rows`
- Evidence:
  - Transaction rows are flattened into memory before display: `modules/vendor/payment_history_view.py:214-236`
  - Both transactions and totals tables call `resizeColumnsToContents()`: `modules/vendor/payment_history_view.py:218-247`
- What code is doing:
  - Entire statement payload is materialized and shown in one shot.
- Why it causes lag:
  - Large vendor histories pay full flattening and layout cost before interaction.
- Trigger:
  - Opening vendor history for long-running vendors
- Recommended fix direction:
  - Use deferred page loading or capped visible rows.
  - Keep manual column widths for big statements.

## Root causes grouped by category

### Full-table loading

- Products list
- Customers list/search
- Vendors list
- Purchases list
- Sales/quotations list
- Most report tabs before pagination stage

### Inefficient table rendering

- Widespread `resizeColumnsToContents()` after each refresh
- `QTableWidget` usage in customer history
- Row-by-row repopulation in history/detail tables

### Repeated database queries

- Product summary N+1
- Customer detail enrichment
- Sales detail panel
- Purchase detail panel
- Vendor selection detail/accounts flow

### Expensive recalculation

- Products summary recomputed across all products
- Expenses totals recalculated after every filter signal
- Report tabs derive secondary metrics after loading full row sets

### Blocking UI thread operations

- All main lists refresh synchronously
- Dashboard refresh synchronous
- Reporting tab refresh synchronous
- History dialogs build large tables synchronously

### Missing pagination / virtualization

- Products
- Customers
- Vendors
- Purchases
- Sales
- Customer history
- Vendor history

### Unnecessary refreshes

- Sales reload on every keypress
- Customers rebuild model on every search change
- Expenses reload on every filter control change
- Reporting refreshes on many date/filter changes

### Signal/event storms

- Customers `selectionChanged` reconnect each rebuild
- Sales `selectionChanged` reconnect each rebuild

### Expensive formatting/styling per row

- Auto-sizing on content
- `QTableWidgetItem` creation for every cell in history views
- Multiple detail widgets updated after each selection

## Modules with lower lag risk

- Inventory Transactions: row limit capped to 50/100/500 and uses `maybe_resize_columns` style guard path in some screens, so risk is lower than Sales/Purchases.
- Inventory Stock Valuation: single-product snapshot, not a mass-row screen.
- Inventory Adjustments recent list: recent rows capped to 50.

These are not the main source of “many records” lag from current code.

## Areas not fully verified

- I excluded tests by design.
- I did not treat README/docs as source of truth.
- I did not benchmark runtime because task was audit-only and repo instructions forbid running tests/benchmarks unless asked.
- Some report repo methods are numerous; I traced refresh paths and data-loading patterns directly, but did not line-audit every single SQL helper behind every report tab.

## Recommended fix directions

These are directions only. No code was changed.

1. Add paging or incremental fetch to large list screens first: Sales, Purchases, Customers, Products.
2. Remove content-based auto-sizing from large datasets. Use fixed widths or one-time/manual widths.
3. Collapse detail-panel N+1 queries into single batched repo calls.
4. Stop rebuilding models for every search/filter event. Reuse models and debounce inputs.
5. Fix repeated `selectionChanged` wiring in Customers and Sales.
6. Lazy-load Reporting tabs and payment sub-tabs on first activation.
7. Move expensive report generation and dashboard aggregates off the UI thread.
8. Replace record-heavy `QTableWidget` screens with model/view tables.
