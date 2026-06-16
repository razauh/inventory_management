# UI Performance Audit

Date: 2026-06-16

## Executive summary

The main UI lag risk is not one single widget. It is a repeated pattern across modules:

- Large result sets are fetched synchronously on the Qt UI thread.
- Several list screens load all matching rows into memory, then let Qt paint/filter the whole model.
- Detail panels often run extra database queries immediately after a row is selected.
- Some screens resize columns by scanning table contents.
- Reports lazy-load tabs, but active report refreshes still run heavy queries and model updates synchronously.

The highest-risk screens are Products, Sales, Customers, Vendors, Expenses, and Reports. Purchases and Inventory have some limits already, but still contain search, selector, and detail-panel paths that can lag as records grow.

No production code was changed for this audit.

## Modules and screens audited

- Products main list, summary, search, details, pricing actions.
- Customers main list, search, detail panel, payment/history entry points.
- Vendors main list, search, detail panel, bank account table, payment/advance entry points.
- Purchases main list, search, selection details, item subtable, payment summary.
- Sales and quotations main list, search, status filter, selection details, item and payment subtables.
- Inventory stock valuation, transactions tab, adjustment tab, product selectors.
- Expenses main list, filters, totals table, category selector.
- Reporting tabs for aging, inventory, expenses, financials, sales, purchases, and payments.
- Dashboard KPI and small table refresh behavior.
- Users and system logs module files were present but empty, so no runtime screen was verified there.

Test files, fixtures, generated graph artifacts, local data, database files, logs, caches, and backups were not inspected.

## Overall performance patterns

### Full-table loading

Several modules fetch every row, or every matching row, without pagination:

- Products calls `repo.list_products()` during controller load and rebuilds the full model.
- Customers calls `repo.list_customers()` and stores all customers in a Qt model.
- Vendors calls `repo.list_vendors()` and stores all vendors in a Qt model.
- Sales calls `repo.search_sales()` even for empty search text, with no `LIMIT`.
- Expenses calls `repo.search_expenses_adv()` with no `LIMIT`.

These paths block the UI until SQLite returns rows, Python converts rows, Qt resets the model, and the view repaints.

### UI-side filtering

Customers, vendors, and products use `QSortFilterProxyModel` over full loaded data. This means each search/filter must scan the in-memory model. With many rows, each keystroke or filter event can cause a full proxy filter pass and repaint.

### Repeated detail queries on selection

Sales, purchases, customers, and vendors run additional database work when a row becomes selected. Initial load often selects the first row, so the first screen render includes both list loading and detail loading.

### Expensive table rendering

Some screens call `resizeColumnsToContents()`. That asks Qt to inspect model data for many cells. On large models this adds a visible paint/layout cost.

### Blocking UI thread work

Most main-list and report reloads run directly from signal handlers, timers, or tab-change handlers on the Qt main thread. Debouncing reduces frequency, but it does not move work off the UI thread.

### Missing pagination or virtualization

Purchase list uses a default 200-row limit. Inventory transactions use a user-selectable limit. Many other major lists do not have a comparable cap.

## Prioritized findings

| Severity | Area | Finding |
|---|---|---|
| Critical | Products | Product list loads all products with heavy aggregate/window SQL and no limit. |
| Critical | Sales | Sales search/list has no limit and selection performs multiple synchronous follow-up queries. |
| High | Customers | Full customer list is loaded and filtered in Qt; detail aggregates run on selection. |
| High | Vendors | Full vendor list is loaded and filtered in Qt; selection reloads details/accounts. |
| High | Expenses | Every filter reload fetches all matching expense rows and recomputes totals. |
| High | Reports | Active report refresh paths run large SQL and table updates on the UI thread. |
| Medium | Purchases | List is capped, but broad search and detail reload still do synchronous work. |
| Medium | Inventory | Transaction list is capped, but product selectors load all products. |
| Medium | Dashboard | Multiple synchronous repo calls and resize-to-contents calls happen during refresh. |

## Per-module findings

### Products

#### P1: Full product list uses heavy SQL and blocks screen load

- Affected files: `modules/product/controller.py`, `database/repositories/products_repo.py`.
- Affected code: `ProductController._build_model()`, `ProductsRepo.list_products()`.
- Trigger: opening Products, reloading after add/edit/delete/import, changing price if reload follows.
- Severity: Critical.
- Evidence:
  - `ProductController.__init__()` calls `_reload()` during construction at `modules/product/controller.py:240-247`.
  - `_build_model()` calls `self.repo.list_products()` and builds a new model/proxy at `modules/product/controller.py:264-281`.
  - `ProductsRepo.list_products()` runs CTEs for UoM labels, latest purchase, latest manual sale, joins `v_stock_on_hand`, and returns all rows at `database/repositories/products_repo.py:62-125`.
- Why this lags:
  - The query scans and groups product UoMs, purchase items, purchases, sale prices, and stock valuation data before the UI can paint.
  - Every product row is converted into a dataclass and installed into a fresh Qt model.
  - No pagination or limit exists.
- Fix direction:
  - Split list columns from computed summary fields.
  - Load first page only.
  - Fetch stock, latest price, and UoM aggregates on demand or in a cached batch.
  - Keep one model/proxy and replace rows instead of rebuilding proxy objects on each reload.

#### P2: Product search filters the full in-memory model

- Affected files: `modules/product/controller.py`, `modules/product/model.py`.
- Affected code: `ProductController._apply_filter()`, `ProductsTableModel.data()`.
- Trigger: each product search text change.
- Severity: High.
- Evidence:
  - Search text connects directly to `_apply_filter()` at `modules/product/controller.py:252-262`.
  - `_apply_filter()` sets a `QRegularExpression` on the proxy at `modules/product/controller.py:286-288`.
  - Product model builds display/user-role values from every matching row on demand at `modules/product/model.py:18-44`.
- Why this lags:
  - Qt proxy filtering must inspect rows already loaded in memory.
  - Large product sets cause repeated data access and repaint work on each keystroke.
- Fix direction:
  - Use debounced server-side search with a row limit.
  - Keep client-side proxy filtering only for small loaded pages.

#### P3: Product summary recomputes over all products on each reload

- Affected file: `modules/product/controller.py`.
- Affected code: `ProductController._update_summary()`.
- Trigger: Products reload.
- Severity: Medium.
- Evidence:
  - `_update_summary()` loops over all product rows and computes low-stock/priced/UoM counts at `modules/product/controller.py:325-345`.
- Why this lags:
  - The loop runs after the already-heavy product query.
  - It scales linearly with product count and blocks the UI thread.
- Fix direction:
  - Use a small aggregate query for counts.
  - Cache summary values and refresh only after product/stock mutations.

### Customers

#### C1: Customer list loads all customers and filters in Qt

- Affected files: `modules/customer/controller.py`, `database/repositories/customers_repo.py`.
- Affected code: `CustomerController._reload()`, `CustomerController._apply_filter()`, `CustomersRepo.list_customers()`.
- Trigger: opening Customers, add/edit/delete reload, search.
- Severity: High.
- Evidence:
  - `_reload()` calls `self.repo.list_customers()` and replaces the full model at `modules/customer/controller.py:83-92`.
  - `list_customers()` selects all customers ordered by ID at `database/repositories/customers_repo.py:41-50`.
  - `_apply_filter()` applies a `QRegularExpression` to the proxy at `modules/customer/controller.py:102-109`.
- Why this lags:
  - All customer rows sit in the UI model.
  - Search does not use `CustomersRepo.search()` in the current controller path.
  - Proxy filtering scans the whole loaded list.
- Fix direction:
  - Use server-side search with `LIMIT/OFFSET`.
  - Keep a visible count based on query metadata, not proxy row count over all rows.

#### C2: Customer detail panel runs aggregate SQL on selection

- Affected files: `modules/customer/controller.py`, `database/repositories/customers_repo.py`.
- Affected code: `CustomerController._update_details()`, `CustomersRepo.get_detail_snapshot()`.
- Trigger: selecting a customer, initial auto-selection after load/filter.
- Severity: High.
- Evidence:
  - Selection change connects to `_update_details()` at `modules/customer/controller.py:73-82`.
  - `_sync_table_state()` calls `_update_details()` after filter and reload at `modules/customer/controller.py:111-119`.
  - `get_detail_snapshot()` runs subqueries for credit balance, sales count, open due sum, last sale, last payment, and last advance at `database/repositories/customers_repo.py:76-120`.
- Why this lags:
  - Each selected row can trigger several aggregate lookups.
  - Reload/filter selects a row and immediately does detail work before the UI is idle.
- Fix direction:
  - Defer details with a short single-shot timer.
  - Batch common detail counts into the list query only when needed.
  - Cache selected customer snapshots until customer/payment data changes.

#### C3: Customer selection restore scans the base model

- Affected file: `modules/customer/controller.py`.
- Affected code: `CustomerController._select_customer_id()`.
- Trigger: reload or filter with a prior selected customer.
- Severity: Medium.
- Evidence:
  - `_select_customer_id()` loops over `range(self.base.rowCount())` to find a matching ID at `modules/customer/controller.py:121-137`.
- Why this lags:
  - Large customer lists make every reload/filter restore perform a linear scan.
- Fix direction:
  - Track an ID-to-source-row map when replacing rows.
  - Avoid restoring selection when filters produce many rows and no selected ID is visible.

### Vendors

#### V1: Vendor list loads all vendors with balance data

- Affected files: `modules/vendor/controller.py`, `database/repositories/vendors_repo.py`.
- Affected code: `VendorController._build_model()`, `VendorsRepo.list_vendors()`.
- Trigger: opening Vendors, reload after add/edit/import/account changes.
- Severity: High.
- Evidence:
  - `_build_model()` calls `self.repo.list_vendors()` and replaces the full model at `modules/vendor/controller.py:85-97`.
  - `list_vendors()` selects all vendors and joins `v_vendor_advance_balance` at `database/repositories/vendors_repo.py:33-47`.
- Why this lags:
  - Vendor row count and balance view cost both grow.
  - All rows are pushed into the Qt model before the screen is ready.
- Fix direction:
  - Use paged vendor listing.
  - Load balances separately for visible rows or selected vendor.

#### V2: Vendor search filters the full model synchronously

- Affected file: `modules/vendor/controller.py`.
- Affected code: `VendorController._apply_filter()`.
- Trigger: every vendor search text change.
- Severity: High.
- Evidence:
  - Search text connects directly to `_apply_filter()` at `modules/vendor/controller.py:70-84`.
  - `_apply_filter()` sets proxy regex and may select row zero at `modules/vendor/controller.py:104-111`.
- Why this lags:
  - Filtering scans the full loaded vendor model on every keystroke.
  - Selecting the first result can also trigger detail/account work.
- Fix direction:
  - Debounce search.
  - Move search into repository query with a result cap.

#### V3: Vendor detail/account work follows selection

- Affected file: `modules/vendor/controller.py`.
- Affected code: `VendorController._update_details()`.
- Trigger: selecting a vendor, initial auto-selection after reload.
- Severity: Medium.
- Evidence:
  - `_reload()` selects row zero after loading at `modules/vendor/controller.py:97-103`.
  - `_update_details()` sets detail data, credit, schedules account reload, and updates account buttons at `modules/vendor/controller.py:144-167`.
- Why this lags:
  - List paint and detail/account refresh happen back-to-back.
  - Large vendor-account tables or slow balance view calls extend selection latency.
- Fix direction:
  - Defer account reload until after the list paint.
  - Cache account rows per vendor during a session.

### Sales

#### S1: Sales and quotation list has no row limit

- Affected files: `modules/sales/controller.py`, `database/repositories/sales_repo.py`.
- Affected code: `SalesController._build_model()`, `SalesRepo.search_sales()`, `SalesRepo.list_sales()`.
- Trigger: opening Sales, switching Sales/Quotations, search, clear filters.
- Severity: Critical.
- Evidence:
  - Search text is debounced but still calls `_reload()` at `modules/sales/controller.py:253-255`.
  - `_build_model()` calls `repo.search_sales(self._search_text, doc_type=self._doc_type)` at `modules/sales/controller.py:522-557`.
  - `search_sales()` builds SQL with no `LIMIT` and fetches all matches at `database/repositories/sales_repo.py:137-178`.
  - `list_sales()` also has no `LIMIT` at `database/repositories/sales_repo.py:119-135`.
- Why this lags:
  - Empty search loads all sales or quotations.
  - Search matching many rows pushes all rows into the model.
  - The work runs on the UI thread.
- Fix direction:
  - Add default page size and explicit paging.
  - Add server-side status filtering instead of proxy-only status filtering.
  - Include total-count query only if needed for UI status text.

#### S2: Sales status filter is client-side over loaded rows

- Affected file: `modules/sales/controller.py`.
- Affected code: `SalesStatusProxy.filterAcceptsRow()`, `SalesController._on_status_filter_changed()`.
- Trigger: changing payment or quotation status filter.
- Severity: High.
- Evidence:
  - Status filter invalidates the proxy at `modules/sales/controller.py:256-328`.
  - `SalesStatusProxy.filterAcceptsRow()` reads source rows and status for each row at `modules/sales/controller.py:35-72`.
- Why this lags:
  - Status filtering scans all loaded sales rows.
  - If the list is unbounded, proxy filtering scales with total row count.
- Fix direction:
  - Apply status in SQL and fetch only the current page.

#### S3: Selection runs multiple synchronous detail queries

- Affected file: `modules/sales/controller.py`.
- Affected code: `SalesController._on_selection_changed()`, `_update_action_states()`, `_sync_details()`.
- Trigger: selecting any sale, initial row selection after reload, mode switch.
- Severity: Critical.
- Evidence:
  - Selection calls `_update_action_states()` then `_sync_details()` at `modules/sales/controller.py:330-333`.
  - `_update_action_states()` calls `_return_eligibility()` and `_financial_action_eligibility()` for sales at `modules/sales/controller.py:335-367`.
  - `_return_eligibility()` calls `get_returnable_quantities()` at `modules/sales/controller.py:384-411`.
  - `_financial_action_eligibility()` fetches sale financials at `modules/sales/controller.py:431-455`.
  - `_sync_details()` loads items, detail summary, payments, credit balance, and financials at `modules/sales/controller.py:692-761`.
- Why this lags:
  - One selection can perform several DB queries and Python calculations.
  - Reload selects row zero at `modules/sales/controller.py:581-599`, so initial list load also runs detail work.
  - Some financial data is requested both for action eligibility and detail payload.
- Fix direction:
  - Fetch a single detail snapshot that includes items, payments, returnability, remaining due, and credit eligibility.
  - Avoid running action eligibility queries before detail data is loaded.
  - Defer detail refresh and cancel stale selection requests.

#### S4: Sales selection restore scans visible rows

- Affected file: `modules/sales/controller.py`.
- Affected code: `SalesController._select_row_by_sale_id()`.
- Trigger: reload with a previous selected sale.
- Severity: Medium.
- Evidence:
  - `_select_row_by_sale_id()` loops over every proxy row until it finds a sale ID at `modules/sales/controller.py:601-615`.
- Why this lags:
  - Large unbounded result sets make reloads do an extra linear scan.
- Fix direction:
  - Maintain sale ID to row index mapping for loaded rows.
  - Prefer preserving selected row only within current page.

### Purchases

#### PU1: Purchase list is capped, but broad search is still expensive

- Affected files: `modules/purchase/controller.py`, `database/repositories/purchases_repo.py`.
- Affected code: `PurchaseController._load_purchase_rows()`, `PurchasesRepo.search_purchases()`.
- Trigger: opening Purchases, search, radio-button search-field changes.
- Severity: Medium.
- Evidence:
  - `_load_purchase_rows()` calls `search_purchases()` or `list_purchases()` at `modules/purchase/controller.py:229-234`.
  - `DEFAULT_LIST_LIMIT = 200` exists at `database/repositories/purchases_repo.py:50`.
  - `search_purchases()` uses broad `LIKE` across ID, date, vendor, status, totals, returned value, net total, paid, and remaining due at `database/repositories/purchases_repo.py:95-148`.
- Why this lags:
  - The row count is capped, but SQLite may still scan and compute many candidate rows before returning 200.
  - Casting numeric values to text and using leading-wildcard `LIKE` cannot use normal indexes well.
- Fix direction:
  - Keep the limit, but use field-specific indexed searches.
  - Remove numeric text matching from default "all" search or make it explicit.
  - Add date/status/vendor filters instead of casting computed totals.

#### PU2: Purchase selection loads a detail snapshot and item subtable

- Affected files: `modules/purchase/controller.py`, `database/repositories/purchases_repo.py`.
- Affected code: `PurchaseController._sync_details()`, `PurchasesRepo.get_purchase_detail_snapshot()`.
- Trigger: selecting a purchase, initial auto-selection after reload/search.
- Severity: Medium.
- Evidence:
  - `_reload()` selects row zero and calls `_sync_details()` at `modules/purchase/controller.py:130-143`.
  - `_sync_details()` calls `repo.get_purchase_detail_snapshot()` and updates details/items/payment summary at `modules/purchase/controller.py:178-221`.
  - `get_purchase_detail_snapshot()` joins totals, returns, latest payment, and then calls `list_items()` at `database/repositories/purchases_repo.py:180-283`.
- Why this lags:
  - The list refresh is followed by detail SQL and item model reset.
  - Large purchases with many items make selection slower.
- Fix direction:
  - Defer detail load.
  - Reuse list row values for immediate panel display and load expensive detail fields after idle.

### Inventory

#### I1: Transactions tab has a row limit, but reloads synchronously on every filter change

- Affected files: `modules/inventory/transactions.py`, `database/repositories/inventory_repo.py`.
- Affected code: `TransactionsView._reload()`, `InventoryRepo.find_transactions()`.
- Trigger: product/date/limit filter changes and Refresh button.
- Severity: Medium.
- Evidence:
  - Product, date, and limit controls connect directly to `_reload()` at `modules/inventory/transactions.py:130-144`.
  - `_reload()` calls `repo.find_transactions(..., limit=self.limit_value)` and replaces the model at `modules/inventory/transactions.py:227-266`.
  - Repository query orders by date and transaction ID with `LIMIT ?` at `database/repositories/inventory_repo.py:233-300`.
- Why this lags:
  - Limits reduce row count, but rapid date changes still run synchronous SQL and model swaps.
  - Sorting and joins still happen on the UI thread.
- Fix direction:
  - Debounce date/product changes.
  - Keep limit.
  - Move reload to a worker if transaction volume is high.

#### I2: Inventory product selectors load every product

- Affected files: `modules/inventory/transactions.py`, `modules/inventory/stock_valuation.py`, `modules/inventory/controller.py`.
- Affected code: `TransactionsView._load_products()`, `StockValuationWidget._load_products()`, `InventoryController._reload_adjustment_products()`.
- Trigger: opening Inventory tabs.
- Severity: Medium.
- Evidence:
  - Transactions product combo selects all products at `modules/inventory/transactions.py:161-191`.
  - Stock valuation selects all products, builds duplicate maps, and creates a `QCompleter` at `modules/inventory/stock_valuation.py:150-240`.
  - Adjustment product combo selects all products at `modules/inventory/controller.py:71-91`.
- Why this lags:
  - Large product tables make opening Inventory pay product-selector setup cost even before a user searches.
  - Completer creation with `MatchContains` over many product labels can be expensive.
- Fix direction:
  - Use async product lookup or typeahead query with a result cap.
  - Cache product labels once per app session and invalidate after product changes.

### Expenses

#### E1: Expense filters fetch all matching rows and recalculate totals

- Affected files: `modules/expense/controller.py`, `database/repositories/expenses_repo.py`.
- Affected code: `ExpenseController._reload()`, `_refresh_totals()`, `ExpensesRepo.search_expenses_adv()`.
- Trigger: opening Expenses, typing search, date/category/amount filter changes.
- Severity: High.
- Evidence:
  - Filter changes are debounced but call `_reload()` at `modules/expense/controller.py:64-82` and `modules/expense/controller.py:139-145`.
  - `_reload()` calls `search_expenses_adv()` and then `_refresh_totals()` at `modules/expense/controller.py:114-137`.
  - `search_expenses_adv()` selects all matching expenses with no limit at `database/repositories/expenses_repo.py:288-333`.
  - `_refresh_totals()` clears and rebuilds a `QStandardItemModel`, then resizes columns at `modules/expense/controller.py:225-259`.
- Why this lags:
  - Every reload runs both detail rows and aggregate totals on the UI thread.
  - No row cap exists.
  - Totals table rebuild and resize happen even if totals are small but query is expensive.
- Fix direction:
  - Page expense rows.
  - Run totals query separately and debounce it more aggressively.
  - Avoid `DATE(column)` in filters if indexed date text can be compared directly.

### Reports

#### R1: Sales and purchase reports page UI rows but still load many rows per key

- Affected files: `modules/reporting/sales_reports.py`, `modules/reporting/purchase_reports.py`.
- Affected code: `SalesReportsTab.refresh()`, `PurchaseReportsTab.refresh()`, `_ensure_loaded()`, `_apply_page()`.
- Trigger: opening report tab, Apply, changing report subtab.
- Severity: High.
- Evidence:
  - Sales reports define `MAX_ROWS_PER_TABLE = 1000` and `PAGE_SIZE = 100` at `modules/reporting/sales_reports.py:101-104`.
  - Sales `refresh()` loads every key in `_TAB_KEYS`, then applies pages at `modules/reporting/sales_reports.py:506-518`.
  - Purchase reports define the same row/page pattern at `modules/reporting/purchase_reports.py:95-98`.
  - Purchase `refresh()` loads every key in `_TAB_KEYS`, then applies pages at `modules/reporting/purchase_reports.py:774-786`.
  - `_apply_page()` shows only a 100-row slice, but `_loaded_rows` keeps the larger list at `modules/reporting/sales_reports.py:596-610` and `modules/reporting/purchase_reports.py:849-863`.
- Why this lags:
  - UI pagination does not prevent SQL and Python from loading up to 1000 rows per report key.
  - Full refresh loads many report keys, not only the visible table.
  - Work is synchronous despite `use_background_refresh` being accepted by constructors.
- Fix direction:
  - Refresh only the active report key by default.
  - Implement real SQL pagination for drilldown/open rows.
  - Use background workers consistently for expensive reports.

#### R2: Reporting controller refreshes active tabs during tab change on UI thread

- Affected file: `modules/reporting/controller.py`.
- Affected code: `ReportingController._on_tab_changed()`, `_safe_refresh()`, `PaymentsTabHost._on_current_changed()`.
- Trigger: switching top-level report tabs or payment subtabs.
- Severity: High.
- Evidence:
  - `_on_tab_changed()` sets wait cursor, ensures the tab widget, then calls `_safe_refresh()` at `modules/reporting/controller.py:384-405`.
  - `_safe_refresh()` calls `refresh_active_page()` or `refresh()` directly at `modules/reporting/controller.py:407-429`.
  - `PaymentsTabHost._on_current_changed()` calls `_refresh_spec()` directly at `modules/reporting/controller.py:203-212`.
- Why this lags:
  - The wait cursor does not stop UI blocking.
  - Tab switches execute report SQL and model updates before control returns to Qt.
- Fix direction:
  - Show stale content immediately, then refresh in a worker.
  - Add cancelable report refresh jobs for tab switches.

#### R3: Vendor aging still loads open items synchronously after snapshot selection

- Affected file: `modules/reporting/vendor_aging_reports.py`.
- Affected code: `VendorAgingTab.refresh()`, `_build_vendor_aging()`, `_load_open_for_row()`.
- Trigger: opening Vendor Aging, changing as-of date, selecting vendor row.
- Severity: Medium.
- Evidence:
  - `refresh()` calls `_build_vendor_aging()`, sets rows, autosizes, selects first row, and loads open rows at `modules/reporting/vendor_aging_reports.py:156-181`.
  - `_build_vendor_aging()` batches vendor headers and credits, then loops vendors at `modules/reporting/vendor_aging_reports.py:183-258`.
  - `_load_open_for_row()` queries headers for selected vendor and rebuilds open table at `modules/reporting/vendor_aging_reports.py:267-310`.
- Why this lags:
  - The batch work is better than N+1, but still runs on the UI thread.
  - Auto-selecting first row immediately triggers a second data load.
- Fix direction:
  - Move aging computation to a worker like Customer Aging does.
  - Defer open-row load until selection settles.

#### R4: Customer aging uses worker for snapshot but not all follow-up work

- Affected file: `modules/reporting/customer_aging_reports.py`.
- Affected code: `CustomerAgingWorker`, `CustomerAgingTab._on_snapshot_computed()`, `_load_invoices_for_row()`.
- Trigger: opening Customer Aging, selecting customer, selecting row.
- Severity: Medium.
- Evidence:
  - `CustomerAgingWorker` computes snapshot off the UI thread at `modules/reporting/customer_aging_reports.py:231-273`.
  - `_on_snapshot_computed()` then sets rows, autosizes, and may call `list_open_invoices()` on the UI thread at `modules/reporting/customer_aging_reports.py:421-442`.
  - `_load_invoices_for_row()` calls `logic.list_open_invoices()` on selection at `modules/reporting/customer_aging_reports.py:524-527`.
- Why this lags:
  - The heaviest snapshot is threaded, but selected-customer invoice loading remains synchronous.
- Fix direction:
  - Also load invoice drilldown in a worker or defer it.

### Dashboard

#### D1: Dashboard refresh performs multiple synchronous repo calls

- Affected files: `modules/dashboard/controller.py`, `modules/dashboard/view.py`.
- Affected code: `DashboardController.refresh()`, `_refresh_secondary()`, `DashboardView.set_top_products()`, `set_quotations()`.
- Trigger: opening Dashboard, changing period.
- Severity: Medium.
- Evidence:
  - `refresh()` calls `summary_metrics()` synchronously and then schedules secondary work at `modules/dashboard/controller.py:112-171`.
  - `_refresh_secondary()` calls payment breakdowns, top products, and expiring quotations synchronously at `modules/dashboard/controller.py:185-207`.
  - `set_top_products()` and `set_quotations()` rebuild `QStandardItemModel` rows and resize columns at `modules/dashboard/view.py:257-279`.
- Why this lags:
  - `QTimer.singleShot(0, ...)` lets Qt process one event, but secondary DB work still runs on the UI thread.
  - Resize-to-contents adds layout cost.
- Fix direction:
  - Move dashboard secondary queries to a worker.
  - Use fixed column widths for small tables.

## Root causes by category

### Full-table loading

- Products, customers, vendors, sales, and expenses have unbounded list fetch paths.
- Purchases and inventory transactions are partially bounded.
- Reports often cap rows after SQL fetch but still load a large in-memory result set.

### Inefficient table rendering

- `resizeColumnsToContents()` appears in products, customers, purchases, sales, expenses, dashboard, payment history, and reporting helper paths.
- This is safe for small models but expensive when model row count grows.

### Repeated database queries

- Sales selection runs returnability, financials, items, payments, and credit calls.
- Customer selection runs aggregate detail snapshot subqueries.
- Purchase selection runs detail snapshot plus items.
- Vendor selection can reload accounts and detail state.

### Expensive recalculation

- Products recompute summary counts over all rows.
- Expenses recompute totals on each reload.
- Reports recompute multiple report keys for one refresh.

### Blocking UI thread operations

- Main-list repository calls run in UI handlers.
- Report tab refreshes run during tab changes.
- Dashboard secondary refresh runs on the UI thread after a zero-delay timer.

### Missing pagination or virtualization

- No pagination found in products, customers, vendors, sales, or expenses.
- Purchases has a default list cap.
- Inventory transaction tab has explicit limits.
- Sales and purchase reports use UI page slices, not true database pagination.

### Signal/event storms

- Search is debounced in customers, purchases, sales, and expenses.
- Products and vendors apply filter directly on each text change.
- Inventory transactions reload directly on every date/product/limit change.

### Expensive formatting/styling per row

- Table models format money and numeric values in `data()`.
- This is normal for Qt models, but costly when paired with large unbounded row sets and column autosizing.

## Recommended fix order

1. Add bounded server-side pagination to Sales, Products, Customers, Vendors, and Expenses.
2. Replace proxy-only search with debounced repository search for Products, Customers, and Vendors.
3. Combine Sales detail/action eligibility data into one detail snapshot and defer it after selection.
4. Remove `resizeColumnsToContents()` from large tables; use fixed/interactive widths after a row threshold.
5. Move report refresh and dashboard secondary queries to background workers.
6. Convert product selectors to on-demand typeahead or cached bounded lookups.
7. Add row-count and query-time logging in development builds only, without telemetry.

## Areas not fully verified

- No local database was inspected, by instruction.
- No profiling was run.
- No tests, builds, linters, formatters, or benchmarks were run.
- Exact query plans were not verified because local data/index state was not inspected.
- `modules/users/*` and `modules/system_logs/*` production files were empty, so no runtime UI behavior was available there.
- Some reporting modules were sampled by refresh paths and table models rather than every SQL branch in `ReportingRepo`.

