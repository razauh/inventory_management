"""Facade for future accounting operations."""

from __future__ import annotations

from decimal import Decimal
from sqlite3 import Connection
from typing import Any

from .dto import (
    PurchaseFinancials,
    PurchaseOutstanding,
    PurchasePaymentRow,
    PurchasePaymentStatus,
    PurchasePaymentSummary,
    PurchaseTotalInputLine,
    PurchaseTotals,
    SupplierRefundMetadata,
    VendorAdvancePayload,
    VendorAdvanceResult,
    VendorBalance,
    VendorCreditLedgerRow,
    VendorOpenPurchase,
    VendorPaymentEffect,
    VendorPaymentMetadata,
    VendorPaymentPayload,
    VendorPaymentResult,
    VendorPurchaseTotals,
    VendorStatement,
)
from .current_rules.purchase_rules import (
    get_purchase_outstanding as get_current_purchase_outstanding,
    get_purchase_payment_history as get_current_purchase_payment_history,
    get_purchase_payment_summary as get_current_purchase_payment_summary,
    get_purchase_payment_status as get_current_purchase_payment_status,
    get_purchase_totals as get_current_purchase_totals,
    preview_purchase_total as preview_current_purchase_total,
    recalculate_purchase_payment_status as recalculate_current_purchase_payment_status,
)
from .current_rules.vendor_rules import (
    get_vendor_advance_balance as get_current_vendor_advance_balance,
    get_vendor_advance_balances as get_current_vendor_advance_balances,
    get_vendor_credit_ledger as get_current_vendor_credit_ledger,
    get_vendor_open_purchases as get_current_vendor_open_purchases,
    get_vendor_purchase_totals as get_current_vendor_purchase_totals,
    get_vendor_statement as get_current_vendor_statement,
    list_vendor_purchases as list_current_vendor_purchases,
    preview_vendor_payment_effect as preview_current_vendor_payment_effect,
    record_vendor_payment_event as record_current_vendor_payment_event,
    record_vendor_advance_event as record_current_vendor_advance_event,
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

    def get_customer_balance(self, customer_id: int) -> None:
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

    def get_purchase_financials(self, purchase_id: int) -> PurchaseFinancials:
        self._not_implemented("get_purchase_financials")

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

    def get_sale_outstanding(self, sale_id: int) -> None:
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

    def get_customer_credit_balance(self, customer_id: int) -> None:
        self._not_implemented("get_customer_credit_balance")

    def get_bank_balance(self, bank_account_id: int) -> None:
        self._not_implemented("get_bank_balance")

    def get_inventory_value(self, product_id: int | None = None) -> None:
        self._not_implemented("get_inventory_value")

    def record_purchase_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_purchase_event")

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

    def record_customer_receipt_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_customer_receipt_event")

    def record_purchase_return_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_purchase_return_event")

    def record_sale_return_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_sale_return_event")

    def record_expense_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_expense_event")

    def record_stock_adjustment_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_stock_adjustment_event")
