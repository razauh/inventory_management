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

#### P1: 

#### P2: 

#### P3:

### Customers

#### C1: 

#### C2: 
#### C3: 

### Vendors

#### V1: 

#### V2: 

#### V3: 

### Sales

#### S1: 
#### S2: 

#### S3: 

#### S4: 

### Purchases

#### PU1: 

#### PU2: 

### Inventory

#### I1: 

#### I2: 

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

#### R1: 

#### R2: 

#### R3:

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

