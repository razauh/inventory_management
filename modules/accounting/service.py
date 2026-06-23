"""Facade for future accounting operations."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection
from typing import Any

from .dto import (
    APSummary,
    BankLedgerRow,
    CustomerBalance,
    CustomerOpenSale,
    CustomerPaymentEffect,
    CustomerPaymentMetadata,
    CustomerPaymentPayload,
    CustomerPaymentResult,
    CustomerReceivableSummary,
    CustomerRefundRow,
    CustomerStatement,
    InventoryAccountingEvent,
    PaymentActivityReport,
    PurchaseFinancials,
    PurchaseInvoiceFinancials,
    PurchaseInventoryPayload,
    PurchaseInventoryResult,
    PurchaseOutstanding,
    PurchasePaymentRow,
    PurchasePaymentStatus,
    PurchasePaymentSummary,
    PurchaseReturnEffect,
    PurchaseReturnInventoryPayload,
    PurchaseReturnInventoryResult,
    PurchaseReturnPayload,
    PurchaseReturnPreviewPayload,
    PurchaseReturnResult,
    PurchaseReturnTotals,
    PurchaseReturnValue,
    PurchaseTotalInputLine,
    PurchaseTotals,
    PurchaseReportBundle,
    QuotationConversionPayload,
    QuotationConversionResult,
    QuotationFinancials,
    SaleCogsSummary,
    SaleFinancialSummary,
    SaleInventoryLine,
    SaleInventoryPayload,
    SaleInventoryResult,
    SaleInvoiceFinancials,
    SaleOutstanding,
    SalePaymentRow,
    SalePaymentStatus,
    SaleTotalInputLine,
    SaleTotals,
    SupplierRefundMetadata,
    SupplierRefundPayload,
    SupplierRefundResult,
    SupplierRefundRow,
    VendorAdvancePayload,
    VendorAdvanceResult,
    VendorBalance,
    VendorCashMovement,
    VendorCreditLedgerRow,
    VendorOpenPurchase,
    VendorPaymentEffect,
    VendorPaymentMetadata,
    VendorPaymentPayload,
    VendorPaymentResult,
    VendorPurchaseTotals,
    VendorStatement,
    VendorAgingReport,
    ExpenseFinancialSummary,
    ExpenseCategoryTotal,
    ExpenseReportLine,
    ExpenseProfitLossSummary,
)
from .reports.ar_ap_summary import (
    get_ap_summary as get_current_ap_summary,
    get_payment_activity as get_current_payment_activity,
    get_vendor_aging as get_current_vendor_aging,
)
from .reports.party_ledger import (
    get_purchase_reports as get_current_purchase_reports,
)
from .current_rules.inventory_rules import (
    get_inventory_accounting_events as get_current_inventory_accounting_events,
    get_purchase_returnable_quantities as get_current_purchase_returnable_quantities,
    get_sale_returnable_quantities as get_current_sale_returnable_quantities,
    record_purchase_inventory_event as record_current_purchase_inventory_event,
    record_purchase_return_inventory_event as record_current_purchase_return_inventory_event,
    record_sale_inventory_event as record_current_sale_inventory_event,
    record_sale_return_inventory_event as record_current_sale_return_inventory_event,
)
from .current_rules.bank_rules import (
    get_bank_ledger as get_current_bank_ledger,
    get_customer_cash_movements as get_current_customer_cash_movements,
    get_vendor_cash_movements as get_current_vendor_cash_movements,
)
from .current_rules.purchase_rules import (
    get_purchase_outstanding as get_current_purchase_outstanding,
    get_purchase_payment_history as get_current_purchase_payment_history,
    get_purchase_payment_summary as get_current_purchase_payment_summary,
    get_purchase_payment_status as get_current_purchase_payment_status,
    get_purchase_financials as get_current_purchase_financials,
    get_purchase_invoice_financials as get_current_purchase_invoice_financials,
    get_purchase_return_totals as get_current_purchase_return_totals,
    get_purchase_return_values as get_current_purchase_return_values,
    get_purchase_totals as get_current_purchase_totals,
    preview_purchase_return_effect as preview_current_purchase_return_effect,
    preview_purchase_total as preview_current_purchase_total,
    record_purchase_return_event as record_current_purchase_return_event,
    recalculate_purchase_payment_status as recalculate_current_purchase_payment_status,
)
from .current_rules.customer_rules import (
    get_customer_aging as get_current_customer_aging,
    get_customer_history as get_current_customer_history,
    get_customer_payment_history as get_current_customer_payment_history,
    get_customer_receivable_summary as get_current_customer_receivable_summary,
    get_customer_refunds as get_current_customer_refunds,
    get_customer_sales_with_items as get_current_customer_sales_with_items,
    get_customer_statement as get_current_customer_statement,
    list_customer_credit_ledger as list_current_customer_credit_ledger,
    list_customer_sale_summaries as list_current_customer_sale_summaries,
    record_customer_credit_application_event as record_current_customer_credit_application_event,
    record_customer_credit_event as record_current_customer_credit_event,
)
from .current_rules.sales_rules import (
    get_latest_sale_payment as get_current_latest_sale_payment,
    get_quotation_financials as get_current_quotation_financials,
    get_sale_cogs as get_current_sale_cogs,
    record_quotation_conversion_event as record_current_quotation_conversion_event,
    get_sale_financial_summary as get_current_sale_financial_summary,
    get_sale_invoice_financials as get_current_sale_invoice_financials,
    get_sale_outstanding as get_current_sale_outstanding,
    get_sale_payment_history as get_current_sale_payment_history,
    get_sale_payment_status as get_current_sale_payment_status,
    get_sale_refunds as get_current_sale_refunds,
    get_sale_return_totals as get_current_sale_return_totals,
    get_sale_return_values as get_current_sale_return_values,
    get_sales_dashboard_metrics as get_current_sales_dashboard_metrics,
    get_sales_profit_summary as get_current_sales_profit_summary,
    get_sale_totals as get_current_sale_totals,
    preview_sale_total as preview_current_sale_total,
    recalculate_sale_payment_status as recalculate_current_sale_payment_status,
    record_customer_payment_event as record_current_customer_payment_event,
    record_sale_return_event as record_current_sale_return_event,
    update_customer_payment_state as update_current_customer_payment_state,
    reopen_customer_payment_state as reopen_current_customer_payment_state,
)
from .current_rules.vendor_rules import (
    get_vendor_advance_balance as get_current_vendor_advance_balance,
    get_vendor_advance_balances as get_current_vendor_advance_balances,
    get_vendor_credit_ledger as get_current_vendor_credit_ledger,
    get_vendor_open_purchases as get_current_vendor_open_purchases,
    get_vendor_purchase_totals as get_current_vendor_purchase_totals,
    get_vendor_statement as get_current_vendor_statement,
    get_supplier_refunds_for_purchase as get_current_supplier_refunds_for_purchase,
    list_vendor_purchases as list_current_vendor_purchases,
    preview_vendor_advance_allocation as preview_current_vendor_advance_allocation,
    preview_vendor_payment_effect as preview_current_vendor_payment_effect,
    record_vendor_advance_with_auto_apply as record_current_vendor_advance_with_auto_apply,
    record_vendor_payment_event as record_current_vendor_payment_event,
    record_vendor_advance_event as record_current_vendor_advance_event,
    record_supplier_refund_event as record_current_supplier_refund_event,
    update_vendor_payment_state as update_current_vendor_payment_state,
)
from .exceptions import AccountingNotImplementedError
from .current_rules.expense_rules import (
    get_expense_financial_summary as get_current_expense_financial_summary,
    list_expense_rows as list_current_expense_rows,
    get_expense_screen_category_totals as get_current_expense_screen_category_totals,
    get_expense_report_category_totals as get_current_expense_report_category_totals,
    get_expense_report_lines as get_current_expense_report_lines,
    get_profit_loss_expense_summary as get_current_profit_loss_expense_summary,
    get_dashboard_expense_total as get_current_dashboard_expense_total,
    record_expense_create_event as record_current_expense_create_event,
    record_expense_update_event as record_current_expense_update_event,
    record_expense_delete_event as record_current_expense_delete_event,
    record_expense_category_create_event as record_current_expense_category_create_event,
    record_expense_category_update_event as record_current_expense_category_update_event,
    record_expense_category_delete_event as record_current_expense_category_delete_event,
)
from .validators import (
    validate_customer_payment_metadata as validate_current_customer_payment_metadata,
    validate_supplier_refund_metadata as validate_current_supplier_refund_metadata,
    validate_vendor_payment_metadata as validate_current_vendor_payment_metadata,
)


class AccountingService:
    """Future single entry point for accounting calculations and postings."""

    def __init__(self, conn: Connection | None = None):
        self.conn = conn

    def _not_implemented(self, operation: str) -> None:
        raise AccountingNotImplementedError(
            f"Accounting operation is not implemented yet: {operation}"
        )

    def get_vendor_balance(self, vendor_id: int) -> VendorBalance:
        self._not_implemented("get_vendor_balance")

    def get_customer_balance(self, customer_id: int) -> CustomerBalance:
        self._not_implemented("get_customer_balance")

    def get_purchase_totals(self, purchase_id: int | str) -> PurchaseTotals:
        if self.conn is None:
            self._not_implemented("get_purchase_totals")
        return get_current_purchase_totals(self.conn, purchase_id)

    def preview_purchase_total(
        self,
        items: tuple[PurchaseTotalInputLine, ...],
        order_discount: Decimal,
    ) -> PurchaseTotals:
        return preview_current_purchase_total(items, order_discount)

    def preview_purchase_return_effect(
        self,
        payload: PurchaseReturnPreviewPayload,
    ) -> PurchaseReturnEffect:
        return preview_current_purchase_return_effect(payload)

    def get_purchase_return_values(
        self,
        purchase_id: int | str,
    ) -> tuple[PurchaseReturnValue, ...]:
        if self.conn is None:
            self._not_implemented("get_purchase_return_values")
        return get_current_purchase_return_values(self.conn, purchase_id)

    def get_purchase_return_totals(
        self,
        purchase_id: int | str,
    ) -> PurchaseReturnTotals:
        if self.conn is None:
            self._not_implemented("get_purchase_return_totals")
        return get_current_purchase_return_totals(self.conn, purchase_id)

    def get_purchase_outstanding(
        self, purchase_id: int | str, *, clamp: bool = False
    ) -> PurchaseOutstanding:
        if self.conn is None:
            self._not_implemented("get_purchase_outstanding")
        return get_current_purchase_outstanding(self.conn, purchase_id, clamp=clamp)

    def get_purchase_remaining_due_header(
        self, purchase_id: int | str
    ) -> PurchaseOutstanding:
        if self.conn is None:
            self._not_implemented("get_purchase_remaining_due_header")
        return get_current_purchase_outstanding(self.conn, purchase_id, clamp=True)

    def get_purchase_payment_status(
        self, purchase_id: int | str
    ) -> PurchasePaymentStatus:
        if self.conn is None:
            self._not_implemented("get_purchase_payment_status")
        return get_current_purchase_payment_status(self.conn, purchase_id)

    def recalculate_purchase_payment_status(
        self, purchase_id: int | str
    ) -> PurchasePaymentStatus:
        if self.conn is None:
            self._not_implemented("recalculate_purchase_payment_status")
        return recalculate_current_purchase_payment_status(self.conn, purchase_id)

    def get_purchase_payment_summary(
        self, purchase_id: int | str
    ) -> PurchasePaymentSummary:
        if self.conn is None:
            self._not_implemented("get_purchase_payment_summary")
        return get_current_purchase_payment_summary(self.conn, purchase_id)

    def get_purchase_payment_history(
        self, purchase_id: int | str
    ) -> tuple[PurchasePaymentRow, ...]:
        if self.conn is None:
            self._not_implemented("get_purchase_payment_history")
        return get_current_purchase_payment_history(self.conn, purchase_id)

    def get_purchase_financials(self, purchase_id: int | str) -> PurchaseFinancials:
        if self.conn is None:
            self._not_implemented("get_purchase_financials")
        return get_current_purchase_financials(self.conn, purchase_id)

    def get_purchase_invoice_financials(
        self,
        purchase_id: int | str,
    ) -> PurchaseInvoiceFinancials:
        if self.conn is None:
            self._not_implemented("get_purchase_invoice_financials")
        return get_current_purchase_invoice_financials(self.conn, purchase_id)

    def get_purchase_reports(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> PurchaseReportBundle:
        if self.conn is None:
            self._not_implemented("get_purchase_reports")
        return get_current_purchase_reports(self.conn, start_date, end_date)

    def validate_vendor_payment_metadata(
        self,
        metadata: VendorPaymentMetadata,
    ) -> None:
        if self.conn is None:
            self._not_implemented("validate_vendor_payment_metadata")
        validate_current_vendor_payment_metadata(self.conn, metadata)

    def validate_supplier_refund_metadata(
        self,
        metadata: SupplierRefundMetadata,
    ) -> None:
        if self.conn is None:
            self._not_implemented("validate_supplier_refund_metadata")
        validate_current_supplier_refund_metadata(self.conn, metadata)

    def validate_customer_payment_metadata(
        self, metadata: CustomerPaymentMetadata
    ) -> None:
        if self.conn is None:
            self._not_implemented("validate_customer_payment_metadata")
        validate_current_customer_payment_metadata(self.conn, metadata)

    def record_supplier_refund_event(
        self,
        payload: SupplierRefundPayload,
    ) -> SupplierRefundResult:
        if self.conn is None:
            self._not_implemented("record_supplier_refund_event")
        return record_current_supplier_refund_event(self.conn, payload)

    def get_supplier_refunds_for_purchase(
        self,
        purchase_id: int | str,
    ) -> tuple[SupplierRefundRow, ...]:
        if self.conn is None:
            self._not_implemented("get_supplier_refunds_for_purchase")
        return get_current_supplier_refunds_for_purchase(self.conn, purchase_id)

    def get_sale_outstanding(self, sale_id: int | str) -> SaleOutstanding:
        if self.conn is None:
            self._not_implemented("get_sale_outstanding")
        return get_current_sale_outstanding(self.conn, sale_id)

    def get_vendor_advance_balance(self, vendor_id: int) -> VendorBalance:
        if self.conn is None:
            self._not_implemented("get_vendor_advance_balance")
        return get_current_vendor_advance_balance(self.conn, vendor_id)

    def get_vendor_advance_balances(
        self, vendor_ids: tuple[int, ...]
    ) -> dict[int, VendorBalance]:
        if self.conn is None:
            self._not_implemented("get_vendor_advance_balances")
        return get_current_vendor_advance_balances(self.conn, vendor_ids)

    def get_vendor_open_purchases(
        self, vendor_id: int
    ) -> tuple[VendorOpenPurchase, ...]:
        if self.conn is None:
            self._not_implemented("get_vendor_open_purchases")
        return get_current_vendor_open_purchases(self.conn, vendor_id)

    def get_vendor_purchase_totals(
        self,
        vendor_id: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> VendorPurchaseTotals:
        if self.conn is None:
            self._not_implemented("get_vendor_purchase_totals")
        return get_current_vendor_purchase_totals(
            self.conn,
            vendor_id,
            date_from,
            date_to,
        )

    def list_vendor_purchases(
        self,
        vendor_id: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[dict, ...]:
        if self.conn is None:
            self._not_implemented("list_vendor_purchases")
        return list_current_vendor_purchases(self.conn, vendor_id, date_from, date_to)

    def get_vendor_statement(
        self,
        vendor_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> VendorStatement:
        if self.conn is None:
            self._not_implemented("get_vendor_statement")
        return get_current_vendor_statement(self.conn, vendor_id, start_date, end_date)

    def get_vendor_aging(self, cutoff_date: str) -> VendorAgingReport:
        if self.conn is None:
            self._not_implemented("get_vendor_aging")
        return get_current_vendor_aging(
            self.conn,
            cutoff_date,
            repo=getattr(self, "_reporting_repo", None),
        )

    def get_ap_summary(self, cutoff_date: str | None = None) -> APSummary:
        if self.conn is None:
            self._not_implemented("get_ap_summary")
        return get_current_ap_summary(
            self.conn,
            cutoff_date,
            repo=getattr(self, "_reporting_repo", None),
        )

    def get_payment_activity(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        date_basis: str = "posting",
    ) -> PaymentActivityReport:
        if self.conn is None:
            self._not_implemented("get_payment_activity")
        return get_current_payment_activity(
            self.conn,
            start_date,
            end_date,
            date_basis=date_basis,
            repo=getattr(self, "_reporting_repo", None),
        )

    def get_customer_credit_balance(self, customer_id: int) -> CustomerBalance:
        if self.conn is None:
            self._not_implemented("get_customer_credit_balance")
        row = self.conn.execute(
            "SELECT COALESCE(balance, 0.0) FROM v_customer_advance_balance WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        return CustomerBalance(
            customer_id=customer_id,
            balance=Decimal(str(row[0])) if row else Decimal("0"),
        )

    def get_sale_totals(self, sale_id: int | str) -> SaleTotals:
        if self.conn is None:
            self._not_implemented("get_sale_totals")
        return get_current_sale_totals(self.conn, sale_id)

    def preview_sale_total(
        self,
        items: tuple[SaleTotalInputLine, ...],
        order_discount: Decimal,
    ) -> SaleTotals:
        return preview_current_sale_total(items, order_discount)

    def get_sale_financial_summary(self, sale_id: int | str) -> SaleFinancialSummary:
        if self.conn is None:
            self._not_implemented("get_sale_financial_summary")
        return get_current_sale_financial_summary(self.conn, sale_id)

    def get_sale_payment_status(self, sale_id: int | str) -> SalePaymentStatus:
        if self.conn is None:
            self._not_implemented("get_sale_payment_status")
        return get_current_sale_payment_status(self.conn, sale_id)

    def recalculate_sale_payment_status(
        self, sale_id: int | str
    ) -> SalePaymentStatus:
        if self.conn is None:
            self._not_implemented("recalculate_sale_payment_status")
        return recalculate_current_sale_payment_status(self.conn, sale_id)

    def get_sale_payment_history(
        self, sale_id: int | str
    ) -> tuple[SalePaymentRow, ...]:
        if self.conn is None:
            self._not_implemented("get_sale_payment_history")
        return get_current_sale_payment_history(self.conn, sale_id)

    def get_latest_sale_payment(
        self, sale_id: int | str
    ) -> SalePaymentRow | None:
        if self.conn is None:
            self._not_implemented("get_latest_sale_payment")
        return get_current_latest_sale_payment(self.conn, sale_id)

    def get_customer_payment_history(
        self, customer_id: int
    ) -> tuple[SalePaymentRow, ...]:
        if self.conn is None:
            self._not_implemented("get_customer_payment_history")
        return get_current_customer_payment_history(self.conn, customer_id)

    def get_customer_open_sales(
        self, customer_id: int
    ) -> tuple[CustomerOpenSale, ...]:
        self._not_implemented("get_customer_open_sales")

    def get_customer_statement(
        self,
        customer_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> CustomerStatement:
        if self.conn is None:
            self._not_implemented("get_customer_statement")
        return get_current_customer_statement(self.conn, customer_id, start_date, end_date)

    def get_customer_history(self, customer_id: int) -> dict[str, Any]:
        if self.conn is None:
            self._not_implemented("get_customer_history")
        return get_current_customer_history(self.conn, customer_id)

    def get_customer_sales_with_items(self, customer_id: int) -> list[dict[str, Any]]:
        if self.conn is None:
            self._not_implemented("get_customer_sales_with_items")
        return get_current_customer_sales_with_items(self.conn, customer_id)

    def get_customer_aging(self, cutoff_date: str) -> CustomerAgingReport:
        if self.conn is None:
            self._not_implemented("get_customer_aging")
        return get_current_customer_aging(self.conn, cutoff_date)

    def record_customer_credit_event(
        self, payload: CustomerCreditPayload
    ) -> CustomerCreditResult:
        if self.conn is None:
            self._not_implemented("record_customer_credit_event")
        return record_current_customer_credit_event(self.conn, payload)

    def list_customer_credit_ledger(
        self, customer_id: int
    ) -> tuple[CustomerCreditLedgerRow, ...]:
        if self.conn is None:
            self._not_implemented("list_customer_credit_ledger")
        return list_current_customer_credit_ledger(self.conn, customer_id)

    def get_customer_refunds(self, customer_id: int) -> tuple[CustomerRefundRow, ...]:
        if self.conn is None:
            self._not_implemented("get_customer_refunds")
        return get_current_customer_refunds(self.conn, customer_id)

    def get_sale_refunds(self, sale_id: int | str) -> tuple[CustomerRefundRow, ...]:
        if self.conn is None:
            self._not_implemented("get_sale_refunds")
        return get_current_sale_refunds(self.conn, sale_id)

    def record_customer_credit_application_event(
        self, payload: CustomerCreditApplicationPayload
    ) -> CustomerCreditApplicationResult:
        if self.conn is None:
            self._not_implemented("record_customer_credit_application_event")
        return record_current_customer_credit_application_event(self.conn, payload)

    def get_customer_receivable_summary(
        self, customer_id: int
    ) -> CustomerReceivableSummary:
        if self.conn is None:
            self._not_implemented("get_customer_receivable_summary")
        return get_current_customer_receivable_summary(self.conn, customer_id)

    def list_customer_sale_summaries(
        self, customer_id: int
    ) -> tuple[dict[str, Any], ...]:
        if self.conn is None:
            self._not_implemented("list_customer_sale_summaries")
        return list_current_customer_sale_summaries(self.conn, customer_id)

    def get_sale_invoice_financials(
        self, sale_id: int | str
    ) -> SaleInvoiceFinancials:
        if self.conn is None:
            self._not_implemented("get_sale_invoice_financials")
        return get_current_sale_invoice_financials(self.conn, sale_id)

    def get_quotation_financials(
        self, quotation_id: int | str
    ) -> QuotationFinancials:
        if self.conn is None:
            self._not_implemented("get_quotation_financials")
        return get_current_quotation_financials(self.conn, quotation_id)

    def validate_quotation_conversion(self, quotation_id: int | str) -> None:
        """Raise ValueError if the quotation is not convertible."""
        if self.conn is None:
            self._not_implemented("validate_quotation_conversion")
        from .current_rules.sales_rules import validate_quotation_conversion as _vqc
        _vqc(self.conn, quotation_id)

    def record_quotation_conversion_event(
        self, payload: QuotationConversionPayload
    ) -> QuotationConversionResult:
        if self.conn is None:
            self._not_implemented("record_quotation_conversion_event")
        return record_current_quotation_conversion_event(self.conn, payload)

    def get_sales_dashboard_metrics(
        self, date_from: str, date_to: str
    ) -> SalesDashboardMetrics:
        if self.conn is None:
            self._not_implemented("get_sales_dashboard_metrics")
        return get_current_sales_dashboard_metrics(self.conn, date_from, date_to)

    def get_bank_balance(self, bank_account_id: int) -> None:
        self._not_implemented("get_bank_balance")

    def get_customer_cash_movements(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[CustomerCashMovement, ...]:
        if self.conn is None:
            self._not_implemented("get_customer_cash_movements")
        return get_current_customer_cash_movements(self.conn, start_date, end_date)

    def get_vendor_cash_movements(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[VendorCashMovement, ...]:
        if self.conn is None:
            self._not_implemented("get_vendor_cash_movements")
        return get_current_vendor_cash_movements(self.conn, start_date, end_date)

    def get_bank_ledger(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        account_id: int | None = None,
    ) -> tuple[BankLedgerRow, ...]:
        if self.conn is None:
            self._not_implemented("get_bank_ledger")
        return get_current_bank_ledger(self.conn, start_date, end_date, account_id)

    def get_inventory_value(self, product_id: int | None = None) -> None:
        self._not_implemented("get_inventory_value")

    def record_purchase_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_purchase_event")

    def record_purchase_inventory_event(
        self,
        payload: PurchaseInventoryPayload,
    ) -> PurchaseInventoryResult:
        if self.conn is None:
            self._not_implemented("record_purchase_inventory_event")
        return record_current_purchase_inventory_event(self.conn, payload)

    def record_purchase_return_inventory_event(
        self,
        payload: PurchaseReturnInventoryPayload,
    ) -> PurchaseReturnInventoryResult:
        if self.conn is None:
            self._not_implemented("record_purchase_return_inventory_event")
        return record_current_purchase_return_inventory_event(self.conn, payload)

    def get_purchase_returnable_quantities(
        self,
        purchase_id: int | str,
    ) -> dict[int, Decimal]:
        if self.conn is None:
            self._not_implemented("get_purchase_returnable_quantities")
        return get_current_purchase_returnable_quantities(self.conn, purchase_id)

    def get_inventory_accounting_events(
        self,
        source_type: str | None = None,
        source_id: int | str | None = None,
    ) -> tuple[InventoryAccountingEvent, ...]:
        if self.conn is None:
            self._not_implemented("get_inventory_accounting_events")
        return get_current_inventory_accounting_events(self.conn, source_type, source_id)

    def record_sale_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_sale_event")

    def preview_vendor_payment_effect(
        self,
        payload: VendorPaymentPayload,
    ) -> VendorPaymentEffect:
        if self.conn is None:
            self._not_implemented("preview_vendor_payment_effect")
        return preview_current_vendor_payment_effect(self.conn, payload)

    def record_vendor_payment_event(
        self,
        payload: VendorPaymentPayload | None = None,
    ) -> VendorPaymentResult:
        if self.conn is None or payload is None:
            self._not_implemented("record_vendor_payment_event")
        return record_current_vendor_payment_event(self.conn, payload)

    def update_vendor_payment_state(
        self,
        payment_id: int,
        *,
        clearing_state: str,
        cleared_date: str | None = None,
        notes: str | None = None,
    ) -> int:
        if self.conn is None:
            self._not_implemented("update_vendor_payment_state")
        return update_current_vendor_payment_state(
            self.conn,
            payment_id,
            clearing_state=clearing_state,
            cleared_date=cleared_date,
            notes=notes,
        )

    def record_vendor_advance_event(
        self,
        payload: VendorAdvancePayload,
    ) -> VendorAdvanceResult:
        if self.conn is None:
            self._not_implemented("record_vendor_advance_event")
        return record_current_vendor_advance_event(self.conn, payload)

    def get_vendor_credit_ledger(
        self,
        vendor_id: int,
    ) -> tuple[VendorCreditLedgerRow, ...]:
        if self.conn is None:
            self._not_implemented("get_vendor_credit_ledger")
        return get_current_vendor_credit_ledger(self.conn, vendor_id)

    def preview_vendor_advance_allocation(
        self,
        vendor_id: int,
        amount: Decimal,
    ) -> dict:
        if self.conn is None:
            self._not_implemented("preview_vendor_advance_allocation")
        return preview_current_vendor_advance_allocation(self.conn, vendor_id, amount)

    def record_vendor_advance_with_auto_apply(
        self,
        payload: VendorAdvancePayload,
    ) -> dict:
        if self.conn is None:
            self._not_implemented("record_vendor_advance_with_auto_apply")
        return record_current_vendor_advance_with_auto_apply(self.conn, payload)

    def record_customer_payment_event(
        self, payload: CustomerPaymentPayload
    ) -> CustomerPaymentResult:
        if self.conn is None:
            self._not_implemented("record_customer_payment_event")
        return record_current_customer_payment_event(self.conn, payload)

    def update_customer_payment_state(
        self,
        payment_id: int,
        *,
        clearing_state: str,
        cleared_date: str | None = None,
        notes: str | None = None,
    ) -> int:
        if self.conn is None:
            self._not_implemented("update_customer_payment_state")
        return update_current_customer_payment_state(
            self.conn, payment_id,
            clearing_state=clearing_state,
            cleared_date=cleared_date,
            notes=notes,
        )

    def reopen_customer_payment_state(
        self,
        payment_id: int,
        *,
        reason: str | None = None,
    ) -> int:
        if self.conn is None:
            self._not_implemented("reopen_customer_payment_state")
        return reopen_current_customer_payment_state(
            self.conn, payment_id, reason=reason,
        )

    def record_purchase_return_event(
        self,
        payload: PurchaseReturnPayload,
    ) -> PurchaseReturnResult:
        if self.conn is None:
            self._not_implemented("record_purchase_return_event")
        return record_current_purchase_return_event(self.conn, payload)

    def get_sale_return_totals(self, sale_id: int | str) -> SaleReturnTotals:
        if self.conn is None:
            self._not_implemented("get_sale_return_totals")
        return get_current_sale_return_totals(self.conn, sale_id)

    def get_sale_return_values(self, sale_id: int | str) -> tuple[SaleReturnValue, ...]:
        if self.conn is None:
            self._not_implemented("get_sale_return_values")
        return get_current_sale_return_values(self.conn, sale_id)

    def record_sale_return_event(self, payload: SaleReturnPayload) -> SaleReturnEffect:
        if self.conn is None:
            self._not_implemented("record_sale_return_event")
        return record_current_sale_return_event(self.conn, payload)

    def record_expense_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_expense_event")

    def get_expense_financial_summary(self, expense_id: int) -> ExpenseFinancialSummary | None:
        if self.conn is None:
            self._not_implemented("get_expense_financial_summary")
        return get_current_expense_financial_summary(self.conn, expense_id)

    def list_expense_rows(
        self,
        query: str = "",
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        category_id: int | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
    ) -> tuple[ExpenseFinancialSummary, ...]:
        if self.conn is None:
            self._not_implemented("list_expense_rows")
        return list_current_expense_rows(
            self.conn,
            query=query,
            date=date,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            amount_min=amount_min,
            amount_max=amount_max,
        )

    def get_expense_screen_category_totals(
        self,
        query: str = "",
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        category_id: int | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
    ) -> tuple[ExpenseCategoryTotal, ...]:
        if self.conn is None:
            self._not_implemented("get_expense_screen_category_totals")
        return get_current_expense_screen_category_totals(
            self.conn,
            query=query,
            date=date,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
            amount_min=amount_min,
            amount_max=amount_max,
        )

    def get_expense_report_category_totals(
        self,
        date_from: str,
        date_to: str,
        category_id: int | None,
    ) -> tuple[ExpenseCategoryTotal, ...]:
        if self.conn is None:
            self._not_implemented("get_expense_report_category_totals")
        return get_current_expense_report_category_totals(
            self.conn,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
        )

    def get_expense_report_lines(
        self,
        date_from: str,
        date_to: str,
        category_id: int | None,
    ) -> tuple[ExpenseReportLine, ...]:
        if self.conn is None:
            self._not_implemented("get_expense_report_lines")
        return get_current_expense_report_lines(
            self.conn,
            date_from=date_from,
            date_to=date_to,
            category_id=category_id,
        )

    def get_dashboard_expense_total(self, date_from: str, date_to: str) -> Decimal:
        if self.conn is None:
            self._not_implemented("get_dashboard_expense_total")
        return get_current_dashboard_expense_total(
            self.conn,
            date_from=date_from,
            date_to=date_to,
        )

    def get_profit_loss_expense_summary(self, date_from: str, date_to: str) -> ExpenseProfitLossSummary:
        if self.conn is None:
            self._not_implemented("get_profit_loss_expense_summary")
        return get_current_profit_loss_expense_summary(
            self.conn,
            date_from=date_from,
            date_to=date_to,
        )

    def validate_expense_input(
        self,
        description: str,
        amount: float,
        date: str,
        category_id: int | None,
    ) -> None:
        if self.conn is None:
            self._not_implemented("validate_expense_input")
        from .validators import validate_expense_input as val_exp
        val_exp(description, amount, date, category_id)

    def record_expense_create_event(
        self,
        description: str,
        amount: float,
        date: str,
        category_id: int | None,
    ) -> int:
        if self.conn is None:
            self._not_implemented("record_expense_create_event")
        return record_current_expense_create_event(
            self.conn,
            description=description,
            amount=amount,
            date=date,
            category_id=category_id,
        )

    def record_expense_update_event(
        self,
        expense_id: int,
        description: str,
        amount: float,
        date: str,
        category_id: int | None,
    ) -> None:
        if self.conn is None:
            self._not_implemented("record_expense_update_event")
        record_current_expense_update_event(
            self.conn,
            expense_id=expense_id,
            description=description,
            amount=amount,
            date=date,
            category_id=category_id,
        )

    def record_expense_delete_event(self, expense_id: int) -> None:
        if self.conn is None:
            self._not_implemented("record_expense_delete_event")
        record_current_expense_delete_event(self.conn, expense_id)

    def validate_expense_category_input(self, name: str) -> None:
        if self.conn is None:
            self._not_implemented("validate_expense_category_input")
        from .validators import validate_expense_category_input as val_cat
        val_cat(name)

    def record_expense_category_create_event(self, name: str) -> int:
        if self.conn is None:
            self._not_implemented("record_expense_category_create_event")
        return record_current_expense_category_create_event(self.conn, name)

    def record_expense_category_update_event(self, category_id: int, name: str) -> None:
        if self.conn is None:
            self._not_implemented("record_expense_category_update_event")
        record_current_expense_category_update_event(self.conn, category_id, name)

    def record_expense_category_delete_event(self, category_id: int) -> None:
        if self.conn is None:
            self._not_implemented("record_expense_category_delete_event")
        record_current_expense_category_delete_event(self.conn, category_id)

    def record_sale_inventory_event(
        self, payload: SaleInventoryPayload
    ) -> SaleInventoryResult:
        if self.conn is None:
            self._not_implemented("record_sale_inventory_event")
        return record_current_sale_inventory_event(self.conn, payload)

    def get_sale_returnable_quantities(
        self, sale_id: int | str
    ) -> dict[int, Decimal]:
        if self.conn is None:
            self._not_implemented("get_sale_returnable_quantities")
        return get_current_sale_returnable_quantities(self.conn, sale_id)

    def record_sale_return_inventory_event(
        self, payload: SaleReturnInventoryPayload
    ) -> SaleReturnInventoryResult:
        if self.conn is None:
            self._not_implemented("record_sale_return_inventory_event")
        return record_current_sale_return_inventory_event(self.conn, payload)

    def get_sale_cogs(self, sale_id: int | str) -> SaleCogsSummary:
        if self.conn is None:
            self._not_implemented("get_sale_cogs")
        return get_current_sale_cogs(self.conn, sale_id)

    def get_sales_profit_summary(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> SalesProfitSummary:
        if self.conn is None:
            self._not_implemented("get_sales_profit_summary")
        return get_current_sales_profit_summary(self.conn, start_date, end_date)

    def record_stock_adjustment_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_stock_adjustment_event")
