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
    QuotationFinancials,
    SaleFinancialSummary,
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
    record_purchase_inventory_event as record_current_purchase_inventory_event,
    record_purchase_return_inventory_event as record_current_purchase_return_inventory_event,
)
from .current_rules.bank_rules import (
    get_bank_ledger as get_current_bank_ledger,
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
from .current_rules.sales_rules import (
    get_sale_totals as get_current_sale_totals,
    preview_sale_total as preview_current_sale_total,
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
from .validators import (
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

    def get_purchase_outstanding(self, purchase_id: int | str) -> PurchaseOutstanding:
        if self.conn is None:
            self._not_implemented("get_purchase_outstanding")
        return get_current_purchase_outstanding(self.conn, purchase_id)

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
        self._not_implemented("get_sale_outstanding")

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
        self._not_implemented("get_customer_credit_balance")

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
        self._not_implemented("get_sale_financial_summary")

    def get_sale_payment_status(self, sale_id: int | str) -> SalePaymentStatus:
        self._not_implemented("get_sale_payment_status")

    def get_sale_payment_history(
        self, sale_id: int | str
    ) -> tuple[SalePaymentRow, ...]:
        self._not_implemented("get_sale_payment_history")

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
        self._not_implemented("get_customer_statement")

    def get_sale_invoice_financials(
        self, sale_id: int | str
    ) -> SaleInvoiceFinancials:
        self._not_implemented("get_sale_invoice_financials")

    def get_quotation_financials(
        self, quotation_id: int | str
    ) -> QuotationFinancials:
        self._not_implemented("get_quotation_financials")

    def get_bank_balance(self, bank_account_id: int) -> None:
        self._not_implemented("get_bank_balance")

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

    def record_customer_receipt_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_customer_receipt_event")

    def record_purchase_return_event(
        self,
        payload: PurchaseReturnPayload,
    ) -> PurchaseReturnResult:
        if self.conn is None:
            self._not_implemented("record_purchase_return_event")
        return record_current_purchase_return_event(self.conn, payload)

    def record_sale_return_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_sale_return_event")

    def record_expense_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_expense_event")

    def record_stock_adjustment_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_stock_adjustment_event")
