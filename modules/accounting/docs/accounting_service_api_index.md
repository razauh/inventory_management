# Accounting Service API Index

Source: `modules/accounting/service.py`

This document lists the public `AccountingService` APIs that are not transaction-history or ledger/history listing APIs.

Excluded from the main list:
- `get_purchase_payment_history`
- `get_sale_payment_history`
- `get_customer_payment_history`
- `get_customer_history`
- `get_vendor_statement`
- `get_payment_activity`
- `get_customer_cash_movements`
- `get_vendor_cash_movements`
- `get_bank_ledger`
- `get_inventory_accounting_events`
- `list_customer_credit_ledger`
- `get_vendor_credit_ledger`

Private helpers such as `_not_implemented`, `_audit`, and `_log_audit_event` are not API surface.

## Service Construction

- `AccountingService(conn: Connection | None = None, *, audit_enabled: bool = True)`
  - Creates the accounting service wrapper around a SQLite connection.

## Vendor and Accounts Payable Reads

- `get_vendor_balance(vendor_id: int) -> VendorBalance`
  - Reads the vendor payable position. (Audit completed)

- `get_vendor_advance_balance(vendor_id: int) -> VendorBalance`
  - Reads one vendor credit/advance balance. (Audit completed)

- `get_vendor_advance_balances(vendor_ids: tuple[int, ...]) -> dict[int, VendorBalance]`
  - Reads vendor credit/advance balances in batch. (Audit completed)

- `get_vendor_open_purchases(vendor_id: int) -> tuple[VendorOpenPurchase, ...]`
  - Lists purchases with remaining payable balance for one vendor. (Audit completed)

- `get_vendor_purchase_totals(vendor_id: int, date_from: str | None = None, date_to: str | None = None) -> VendorPurchaseTotals`
  - Summarizes purchase totals for one vendor and optional date range. (Audit completed)

- `list_vendor_purchases(vendor_id: int, date_from: str | None = None, date_to: str | None = None) -> tuple[dict, ...]`
  - Lists vendor purchases for optional date range. (Audit completed)

- `get_vendor_aging(cutoff_date: str) -> VendorAgingReport`
  - Builds AP aging as of a cutoff date. (Audit completed)

- `get_ap_summary(cutoff_date: str | None = None) -> APSummary`
  - Builds AR/AP summary totals. (Audit completed)

## Purchase Reads and Previews

- `get_purchase_totals(purchase_id: int | str) -> PurchaseTotals`
  - Reads canonical purchase totals. (Audit completed)

- `preview_purchase_total(items: tuple[PurchaseTotalInputLine, ...], order_discount: Decimal) -> PurchaseTotals`
  - Calculates purchase totals before persistence. (Audit completed)

- `preview_purchase_return_effect(payload: PurchaseReturnPreviewPayload) -> PurchaseReturnEffect`
  - Calculates purchase return effect before persistence. (Audit completed)

- `get_purchase_return_values(purchase_id: int | str) -> tuple[PurchaseReturnValue, ...]`
  - Reads valued purchase return lines. (Audit completed)

- `get_purchase_return_totals(purchase_id: int | str) -> PurchaseReturnTotals`
  - Summarizes returned purchase quantity and value. (Audit completed)

- `get_purchase_outstanding(purchase_id: int | str, *, clamp: bool = False) -> PurchaseOutstanding`
  - Reads payable outstanding for a purchase. (Audit completed)

- `get_purchase_remaining_due_header(purchase_id: int | str) -> PurchaseOutstanding`
  - Reads clamped purchase remaining due for UI header use. (Audit completed)

- `get_purchase_payment_status(purchase_id: int | str) -> PurchasePaymentStatus`
  - Reads calculated purchase payment status.

- `recalculate_purchase_payment_status(purchase_id: int | str) -> PurchasePaymentStatus`
  - Recalculates and persists purchase payment status.

- `get_purchase_payment_summary(purchase_id: int | str) -> PurchasePaymentSummary`
  - Reads payment summary for purchase detail panels.

- `get_purchase_financials(purchase_id: int | str) -> PurchaseFinancials`
  - Reads purchase financial summary.

- `get_purchase_invoice_financials(purchase_id: int | str) -> PurchaseInvoiceFinancials`
  - Builds purchase invoice financial context.

- `get_purchase_reports(start_date: str | None = None, end_date: str | None = None) -> PurchaseReportBundle`
  - Builds purchase reporting bundle.

- `get_purchase_returnable_quantities(purchase_id: int | str, *, stock_aware: bool = False) -> dict[int, Decimal]`
  - Reads remaining returnable quantity per purchase item.

## Vendor Payment and Credit Commands

- `validate_vendor_payment_metadata(metadata: VendorPaymentMetadata) -> None`
  - Validates vendor payment method/account metadata.

- `validate_supplier_refund_metadata(metadata: SupplierRefundMetadata) -> None`
  - Validates supplier refund method/account metadata.

- `record_supplier_refund_event(payload: SupplierRefundPayload) -> SupplierRefundResult`
  - Records a supplier refund and audit event.

- `get_supplier_refunds_for_purchase(purchase_id: int | str) -> tuple[SupplierRefundRow, ...]`
  - Reads supplier refunds for one purchase.

- `record_purchase_event(event_type: str, payload: Any) -> Any`
  - Dispatches purchase-side accounting events.

- `record_purchase_inventory_event(payload: PurchaseInventoryPayload) -> PurchaseInventoryResult`
  - Posts purchase inventory movement.

- `record_purchase_return_inventory_event(payload: PurchaseReturnInventoryPayload) -> PurchaseReturnInventoryResult`
  - Posts purchase return inventory movement.

- `preview_vendor_payment_effect(payload: VendorPaymentPayload) -> VendorPaymentEffect`
  - Calculates vendor payment effect before persistence.

- `record_vendor_payment_event(payload: VendorPaymentPayload | None = None) -> VendorPaymentResult`
  - Records vendor payment and audit event.

- `update_vendor_payment_state(payment_id: int, *, clearing_state: str, cleared_date: str | None = None, notes: str | None = None) -> int`
  - Updates vendor payment clearing state.

- `record_vendor_advance_event(payload: VendorAdvancePayload) -> VendorAdvanceResult`
  - Records vendor advance/credit and audit event.

- `preview_vendor_advance_allocation(vendor_id: int, amount: Decimal) -> dict`
  - Previews vendor advance allocation against open purchases.

- `record_vendor_advance_with_auto_apply(payload: VendorAdvancePayload) -> dict`
  - Records vendor advance and auto-applies it.

- `record_purchase_return_event(payload: PurchaseReturnPayload) -> PurchaseReturnResult`
  - Records full purchase return business event.

## Customer and Accounts Receivable Reads

- `get_customer_balance(customer_id: int) -> CustomerBalance`
  - Reads customer receivable balance.

- `get_sale_outstanding(sale_id: int | str) -> SaleOutstanding`
  - Reads sale outstanding balance.

- `get_customer_credit_balance(customer_id: int) -> CustomerBalance`
  - Reads customer credit balance.

- `get_customer_open_sales(customer_id: int) -> tuple[CustomerOpenSale, ...]`
  - Placeholder API. Currently raises `AccountingNotImplementedError`.

- `get_customer_statement(customer_id: int, start_date: str | None = None, end_date: str | None = None) -> CustomerStatement`
  - Builds customer credit statement.

- `get_customer_sales_with_items(customer_id: int) -> list[dict[str, Any]]`
  - Reads customer sales with item lines.

- `get_customer_aging(cutoff_date: str) -> CustomerAgingReport`
  - Builds AR aging as of a cutoff date.

- `get_customer_refunds(customer_id: int) -> tuple[CustomerRefundRow, ...]`
  - Reads refunds for one customer.

- `get_customer_receivable_summary(customer_id: int) -> CustomerReceivableSummary`
  - Reads customer receivable summary.

- `list_customer_sale_summaries(customer_id: int) -> tuple[dict[str, Any], ...]`
  - Lists sale summaries for one customer.

## Sales Reads and Previews

- `get_sale_totals(sale_id: int | str) -> SaleTotals`
  - Reads canonical sale totals.

- `preview_sale_total(items: tuple[SaleTotalInputLine, ...], order_discount: Decimal) -> SaleTotals`
  - Calculates sale totals before persistence.

- `preview_sale_return_value(payload: SaleReturnPreviewPayload) -> Decimal`
  - Calculates sale return value before persistence.

- `get_sale_financial_summary(sale_id: int | str) -> SaleFinancialSummary`
  - Reads sale financial summary.

- `get_sale_payment_status(sale_id: int | str) -> SalePaymentStatus`
  - Reads calculated sale payment status.

- `recalculate_sale_payment_status(sale_id: int | str) -> SalePaymentStatus`
  - Recalculates and persists sale payment status.

- `get_latest_sale_payment(sale_id: int | str) -> SalePaymentRow | None`
  - Reads latest payment for one sale.

- `get_sale_invoice_financials(sale_id: int | str) -> SaleInvoiceFinancials`
  - Builds sale invoice financial context.

- `get_quotation_financials(quotation_id: int | str) -> QuotationFinancials`
  - Builds quotation financial context.

- `validate_quotation_conversion(quotation_id: int | str) -> None`
  - Validates quotation conversion eligibility.

- `get_sales_dashboard_metrics(date_from: str, date_to: str) -> SalesDashboardMetrics`
  - Reads sales dashboard metrics.

- `get_sale_return_totals(sale_id: int | str) -> SaleReturnTotals`
  - Reads sale return totals.

- `get_sale_return_values(sale_id: int | str) -> tuple[SaleReturnValue, ...]`
  - Reads valued sale return lines.

- `get_sale_returnable_quantities(sale_id: int | str) -> dict[int, Decimal]`
  - Reads remaining returnable quantity per sale item.

- `get_sale_cogs(sale_id: int | str) -> SaleCogsSummary`
  - Reads COGS summary for a sale.

- `get_sales_profit_summary(start_date: str | None = None, end_date: str | None = None) -> SalesProfitSummary`
  - Reads sales profit summary.

## Customer Payment and Credit Commands

- `validate_customer_payment_metadata(metadata: CustomerPaymentMetadata) -> None`
  - Validates customer payment method/account metadata.

- `record_sale_event(event_type: str, payload: Any) -> Any`
  - Dispatches sale-side accounting events.

- `record_customer_credit_event(payload: CustomerCreditPayload) -> CustomerCreditResult`
  - Records customer credit and audit event.

- `record_customer_credit_application_event(payload: CustomerCreditApplicationPayload) -> CustomerCreditApplicationResult`
  - Applies customer credit to a sale.

- `record_customer_payment_event(payload: CustomerPaymentPayload) -> CustomerPaymentResult`
  - Records customer payment and audit event.

- `update_customer_payment_state(payment_id: int, *, clearing_state: str, cleared_date: str | None = None, notes: str | None = None) -> int`
  - Updates customer payment clearing state.

- `reopen_customer_payment_state(payment_id: int, *, reason: str | None = None) -> int`
  - Reopens a customer payment state.

- `record_quotation_conversion_event(payload: QuotationConversionPayload) -> QuotationConversionResult`
  - Converts quotation to sale and records audit event.

- `record_sale_return_event(payload: SaleReturnPayload | None = None) -> SaleReturnEffect`
  - Records full sale return settlement event.

- `record_sale_inventory_event(payload: SaleInventoryPayload) -> SaleInventoryResult`
  - Posts sale inventory movement.

- `record_sale_return_inventory_event(payload: SaleReturnInventoryPayload) -> SaleReturnInventoryResult`
  - Posts sale return inventory movement.

## Bank and Inventory Reads

- `get_bank_balance(bank_account_id: int) -> BankBalance`
  - Reads one bank account balance.

- `get_inventory_value(product_id: int | None = None) -> InventoryValue | tuple[InventoryValue, ...]`
  - Reads current inventory valuation for one product or all products.

## Inventory Commands

- `record_stock_adjustment_event(payload: StockAdjustmentPayload) -> StockAdjustmentResult`
  - Records inventory stock adjustment and audit event.

## Expense Reads

- `get_expense_financial_summary(expense_id: int) -> ExpenseFinancialSummary | None`
  - Reads one expense financial summary.

- `list_expense_rows(query: str = "", date: str | None = None, date_from: str | None = None, date_to: str | None = None, category_id: int | None = None, amount_min: float | None = None, amount_max: float | None = None) -> tuple[ExpenseFinancialSummary, ...]`
  - Lists expense rows with filters.

- `get_expense_screen_category_totals(query: str = "", date: str | None = None, date_from: str | None = None, date_to: str | None = None, category_id: int | None = None, amount_min: float | None = None, amount_max: float | None = None) -> tuple[ExpenseCategoryTotal, ...]`
  - Reads category totals for the expense screen.

- `get_expense_report_category_totals(date_from: str, date_to: str, category_id: int | None) -> tuple[ExpenseCategoryTotal, ...]`
  - Reads category totals for expense reports.

- `get_expense_report_lines(date_from: str, date_to: str, category_id: int | None) -> tuple[ExpenseReportLine, ...]`
  - Reads expense report lines.

- `get_dashboard_expense_total(date_from: str, date_to: str) -> Decimal`
  - Reads dashboard expense total.

- `get_profit_loss_expense_summary(date_from: str, date_to: str) -> ExpenseProfitLossSummary`
  - Reads expense summary for profit/loss.

## Expense Commands

- `record_expense_event(event_type: str, payload: Any = None) -> Any`
  - Dispatches expense create, update, and delete events.

- `validate_expense_input(description: str, amount: float, date: str, category_id: int | None) -> None`
  - Validates expense input.

- `record_expense_create_event(description: str, amount: float, date: str, category_id: int | None) -> int`
  - Creates expense and audit event.

- `record_expense_update_event(expense_id: int, description: str, amount: float, date: str, category_id: int | None) -> None`
  - Updates expense and audit event.

- `record_expense_delete_event(expense_id: int) -> None`
  - Deletes expense and audit event.

- `validate_expense_category_input(name: str) -> None`
  - Validates expense category input.

- `record_expense_category_create_event(name: str) -> int`
  - Creates expense category and audit event.

- `record_expense_category_update_event(category_id: int, name: str) -> None`
  - Updates expense category and audit event.

- `record_expense_category_delete_event(category_id: int) -> None`
  - Deletes expense category and audit event.
