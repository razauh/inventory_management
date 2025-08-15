# Got it. Here’s the end-to-end picture of how **Sales** and **Sale Returns** work in your app, organized by concept and by file. No code—just the logic and responsibilities.

# ---

# # 1) Data model & system behavior (from `schema.py`)

# ### Core entities

# * **customers, vendors, users, products, uoms (units of measure)** — standard masters.
# * **product\_uoms** — per-product UoMs with:

#   * exactly **one base UoM** (`is_base=1`, `factor_to_base=1`)
#   * any number of alternates (each has `factor_to_base>0`)
#   * unique constraint & trigger enforce those rules.

# ### Sales documents

# * **sales (header)**: `sale_id`, `customer_id`, `date`, `total_amount` (already net of order-level discount), `order_discount`, `payment_status` (`paid/partial/unpaid`), `paid_amount`, `notes`, `created_by`, plus `source_type/id`.
# * **sale\_items (lines)**: product, qty, uom, `unit_price`, `item_discount` (per unit).

# ### Inventory ledger & costing

# * **inventory\_transactions**: the single source of truth for stock movement.

#   * Types: `purchase`, `sale`, `sale_return`, `purchase_return`, `adjustment`.
#   * Every sale line inserts a `sale` ledger row; every return inserts a `sale_return` row.
#   * A validation trigger enforces: positive qty for non-adjustments, correct references, and product/UoM consistency with the referenced line.

# * **stock\_valuation\_history**: moving-average costing snapshot after each inventory transaction.

#   * A big **AFTER INSERT** trigger on `inventory_transactions`:

#     * Converts qty into **base UoM** using `product_uoms.factor_to_base`.
#     * Recomputes on-hand qty and **running average unit cost**.
#     * On `purchase`, it blends old value with new purchase cost (UoM-aware); other types adjust qty at the existing average cost.
#   * View **`v_stock_on_hand`** returns the latest quantity/value per product.

# ### Financial views

# * **`sale_detailed_totals`** (important for returns): gives

#   * `subtotal_before_order_discount` = Σ(qty × unit\_price − item\_discount) across lines
#   * `calculated_total_amount` = that subtotal − `order_discount`
# * **`sale_item_cogs`**: COGS for each sale item using running-average at sale date (UoM-aware).
# * **`profit_loss_view`**: month buckets = sales revenue − COGS − expenses.

# ---

# # 2) Repository layer (from `sales_repo.py`)

# ### Data carriers

# * `SaleHeader`, `SaleItem` dataclasses mirror the header/line payloads used by the controller.

# ### Reads

# * `list_sales()` → recent sales with joined customer name and money fields as REALs.
# * `search_sales(query, date)` → filter by SO or customer name and/or date (for the returns UI).
# * `get_header(sid)` → raw sales header.
# * `list_items(sid)` → line items with product & uom names, typed numbers.

# ### Writes (sales lifecycle)

# * **Create sale**:

#   1. Insert header.
#   2. Insert each line.
#   3. For each line, insert an `inventory_transactions` row of type **`sale`** referencing that line.

#      * The after-insert trigger updates stock on hand & moving-average cost.

# * **Update sale**:

#   1. Update header fields.
#   2. Delete prior sale content: all `inventory_transactions` for this sale, then all lines.
#   3. Re-insert fresh lines and corresponding `sale` inventory rows.

# * **Delete sale**:

#   * Delete sale’s inventory rows → delete lines → delete header.

# ### Returns (inventory + money helpers)

# * **record\_return(sid, date, created\_by, lines, notes)**:

#   * Inserts **`sale_return`** inventory rows for the specified `sale_items.item_id` with the returned qty (UoM-consistent with the original line).
#   * The valuation trigger adjusts on-hand at existing moving-average cost.

# * **sale\_return\_totals(sale\_id)**:

#   * Aggregates returned qty and returned value (= Σ qty\_returned × (unit\_price − item\_discount)) across the `sale_return` rows for that sale.

# ### Payments

# * **apply\_payment(sid, amount)**: increases `paid_amount`, sets `payment_status` accordingly.
# * **apply\_refund(sid, amount)**: reduces `paid_amount` (floors at 0), re-derives `payment_status`.

# ### Small helper we added

# * **get\_sale\_totals(sid)** (new): reads `sale_detailed_totals` view to get the canonical:

#   * `net_subtotal` (before order discount)
#   * `total_after_od` (after order discount)
#   * Used by the Return dialog to prorate order discount correctly.

# ---

# # 3) UI & interaction flow (by file)

# ## `sales/view.py` (container view)

# * Toolbar: **New**, **Edit**, **Return**, search box.
# * Split view:

#   * Left: main sales table + a secondary table for the selected sale’s lines.
#   * Right: **SaleDetails** panel.

# ## `sales/model.py`

# * **SalesTableModel**: columns = ID, Date, Customer, Total, Paid, Status. Formats money.
# * **SaleItemsModel**: columns = #, Product, Qty, Unit Price, Discount, Line Total (computed as qty × (price − item\_discount)).

# ## `sales/items.py`

# * **SaleItemsView**: a thin wrapper that hosts the table and model, and exposes `set_rows()`.

# ## `sales/details.py`

# * **SaleDetails** panel shows:

#   * core fields (ID, date, customer)
#   * `Total`, `Order Discount`, `Total Discount` (order + summed line-discount)
#   * placeholders for **Returned Qty**, **Returned Value**, and **Net (after returns)** (UI labels exist; filling those numbers depends on controller providing them)
#   * `Paid`, `Remaining`, and `Status`.

# ## `sales/form.py` (Create/Edit sale dialog)

# * **Header**: select or add customer (with phone), date (defaults to today), order-level discount, notes, optional initial payment (amount + method).
# * **Items grid** (each row):

#   * Product selector
#   * **Base UoM** label and **Alt UoM** combo (enabled only when alternates exist for that product)
#   * **Avail** (current on-hand in the selected UoM)
#   * **Qty** (editable)
#   * **Unit Price** (displayed per selected UoM; sourced from latest base sale price × UoM factor)
#   * **Discount** (per-unit)
#   * **Margin** (total margin for that line = qty × \[(unit − disc) − cost\_in\_selected\_uom]); highlighted red if negative
#   * **Line Total** (qty × (unit − disc))
#   * Delete button for the row
# * **Totals strip** at the bottom:

#   * Subtotal (raw) = Σ qty × unit\_price (after UoM selection, before discount)
#   * Line Discount total = Σ qty × per-unit discount
#   * Order Discount (the header field)
#   * Total Discount (line + order)
#   * **Total** = Subtotal − (Line + Order)
# * **Validation** on OK:

#   * Customer required.
#   * Each row must have product, qty > 0, unit > 0, discount ≥ 0.
#   * **Oversell guard**: qty ≤ available (in current UoM). Violations are highlighted and listed.
#   * On success, returns a payload with normalized line data (`uom_id` = base or selected alt), header totals, and optional initial payment.

# ## `sales/return_form.py` (Sale Return dialog)

# * **Search** pane: query by SO or customer, optional exact date; shows a grid of matching sales (SO/date/customer/Total/Paid).

# * Selecting a sale loads its lines into the lower grid:

#   * `Qty Sold`, `Unit Price` **net of line discount** (i.e., unit − item\_discount), and an editable `Qty Return`.

# * **Order-level discount proration**:

#   * The dialog gets **canonical totals** via `SalesRepo.get_sale_totals()`:

#     * `net_subtotal` = Σ qty × (unit − item\_discount), *before* order discount
#     * `total_after_od` = net\_subtotal − order\_discount
#   * It computes **order\_factor = total\_after\_od / net\_subtotal** (fallback 1.0 if denominator is 0).
#   * Each line’s **Line Refund** = `qty_return × (unit − item_discount) × order_factor`.
#   * **Overshoot protection**: you cannot return more than the `Qty Sold`; that cell turns red and the line ignores amounts.

# * **Whole-order toggle**: fills `Qty Return` = `Qty Sold` for all lines.

# * **Money in the footer** (post-update we agreed on):

#   * **Returned Value** = Σ line refunds (this is the actual value of goods being reversed, already after the order-level discount is prorated).
#   * **Cash Refund (max)** = `min(Returned Value, Paid)` — the most you can give back in cash immediately, based on how much the customer has already paid.
#   * If **Paid = 0**, **Refund now?** is disabled (no cash out); the returned value just reduces the outstanding balance.
#   * Context note tells the operator when the cash refund is capped by Paid.

# * **Payload on OK**:

#   * `sale_id`
#   * `lines` = \[{`item_id`, `qty_return`}…] for valid rows only
#   * `refund_now` (checkbox state)
#   * `refund_amount` = the **Returned Value** (already after proration).
#     The controller decides the actual **cash** to pay now and how much to apply to the balance.

# ---

# # 4) Controller orchestration (from `sales/controller.py`)

# ### Common

# * Generates `sale_id` as `SOYYYYMMDD-####`.
# * Wires view actions (New/Edit/Return), search filtering via `QSortFilterProxyModel`, table selection syncing.

# ### Create sale (`_add`)

# * Opens **SaleForm**.
# * Derives `payment_status` from initial payment vs total.
# * Annotates notes with an initial payment tag if provided.
# * Calls `SalesRepo.create_sale()` (header, lines, and per-line sale inventory rows).
# * UI refresh + “Saved” info.

# ### Edit sale (`_edit`)

# * Preloads existing line items and header fields into **SaleForm**.
# * On save, calls `SalesRepo.update_sale()` (rebuilds lines + inventory rows).
# * UI refresh + “Saved” info.

# ### Delete sale (`_delete`)

# * Not wired by default (commented), but implementation deletes inventory rows, lines, and header.

# ### **Return** (`_return`) — inventory + money

# 1. Open **SaleReturnForm** and read payload.
# 2. Map the payload’s `item_id`s to full line records; build **`lines`** for inventory.
# 3. Call `SalesRepo.record_return()`:

#    * Inserts `sale_return` inventory rows (valuation trigger adjusts on-hand and keeps the average cost unchanged).
# 4. Money logic (the key business rules we finalized):

#    * Let **`refund_amount`** = **Returned Value** (already after order discount proration from the dialog).

#    * Look up current header to get `total_amount` (**this is the post-order-discount amount**) and `paid_amount`.

#    * **If “Refund now?”**:

#      * **Cash refund** = `min(refund_amount, paid_before)`.
#      * Apply it via `SalesRepo.apply_refund()` (reduces `paid_amount`, re-derives `payment_status`).
#      * The remaining non-cash part (**credit\_part** = `refund_amount − cash_refund`) proceeds to balance reduction.

#    * **Reduce balance (never below zero)**:

#      * Refresh `paid_after`.
#      * `balance_before = max(0, total_before − paid_after)`.
#      * `apply_to_balance = min(credit_part, balance_before)`.
#      * `new_total = max(0, total_before − apply_to_balance)`.
#      * Update `sales.total_amount = new_total` and recompute `payment_status` from `paid_after` vs `new_total`.
#      * If any **leftover\_credit** still remains (i.e., you returned more value than the sale’s remaining balance), it is recorded as a **note** (`[Credit memo X]`) until a proper customer-ledger module exists.

#    * If **all sold quantities were returned**, append a `[Full return]` note.

#    * Show a friendly summary (what was refunded in cash, how much balance was reduced, and any credit memo).

# **Resulting behavior**

# * **Paid = 0 & whole return** → no cash out; `total_amount` is reduced to 0; `payment_status` becomes `unpaid` → `paid` (if `paid_after >= new_total`) or stays appropriate.
# * **Partial return & partial payment** → cash refund is capped by Paid; the remainder reduces outstanding balance; statuses adjust correctly; never creates negative balances or accidental over-payments.
# * **Full paid & full return** → cash up to the full `paid_amount`; any residual (if numbers drift due to rounding) only reduces `total_amount`; no negative totals.

# ---

# # 5) Business rules captured

# * **Per-unit vs order-discount**:

#   * Line totals and margins use **line discount** at the per-unit level.
#   * The **order-level discount** is handled once at the header and **prorated** across returns via `order_factor = total_after_od / net_subtotal`.
#   * This ensures returned amounts always match what the customer actually owed/paid after discounts.

# * **UoM awareness everywhere**:

#   * The sale form presents prices/availability in the selected UoM; cost/margin convert from base using `factor_to_base`.
#   * Inventory ledger always carries qty in the specified UoM and converts to base for valuation.

# * **Integrity guards**:

#   * You can’t oversell in the UI (validation).
#   * The DB refuses inventory rows that don’t match the originating line’s product/UoM or that have non-positive qty (except adjustments).
#   * Only one base UoM per product; invalid factors are blocked by triggers.

# * **Financial accuracy**:

#   * Payment status is **derived**, never free-typed.
#   * Cash refunds are **capped by Paid**; the remainder reduces balance, not paid.
#   * No negative totals or balances are created; extra value becomes a placeholder **credit memo** note.

# ---

# # 6) What changed in our updates (so you know the deltas)

# * **Return dialog math & display**

#   * Uses `SalesRepo.get_sale_totals()` (via the `sale_detailed_totals` view) to compute the proration factor reliably.
#   * Shows **two numbers** in the footer:

#     * **Returned Value** (after OD proration; equals the sum of the “Line Refund” column).
#     * **Cash Refund (max)** = `min(Returned Value, Paid)` to avoid confusion.
#   * Disables **Refund now?** when `Paid = 0`.
#   * Context note clarifies when the cash refund is capped.

# * **Controller money logic**

#   * Cash path: **min(returned\_value, paid\_before)** then `apply_refund()`.
#   * Non-cash path: reduce **outstanding balance only**, never below zero; recalc status from `paid_after` vs `new_total`.
#   * Any extra beyond the balance is stored as a simple **credit memo** in notes (until you add a proper customer ledger).
#   * Adds `[Full return]` note when appropriate.

# ---

# That’s the complete functional picture: how data flows from UI to repo to DB, how stock and valuation move, how discounts and returns are computed, and how payments/refunds/balance are enforced. If you’d like, I can also map this to a few concrete scenarios (e.g., partial return with partial payment, fully unpaid full return) and show the exact field transitions step-by-step.
