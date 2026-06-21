"""Facade for future accounting operations."""

from __future__ import annotations

from typing import Any

from .dto import (
    PurchaseFinancials,
    PurchaseOutstanding,
    PurchasePaymentStatus,
    PurchaseTotals,
    VendorBalance,
    VendorOpenPurchase,
    VendorStatement,
)
from .exceptions import AccountingNotImplementedError


class AccountingService:
    """Future single entry point for accounting calculations and postings."""

    def _not_implemented(self, operation: str) -> None:
        raise AccountingNotImplementedError(
            f"Accounting operation is not implemented yet: {operation}"
        )

    def get_vendor_balance(self, vendor_id: int) -> VendorBalance:
        self._not_implemented("get_vendor_balance")

    def get_customer_balance(self, customer_id: int) -> None:
        self._not_implemented("get_customer_balance")

    def get_purchase_totals(self, purchase_id: int) -> PurchaseTotals:
        self._not_implemented("get_purchase_totals")

    def get_purchase_outstanding(self, purchase_id: int) -> PurchaseOutstanding:
        self._not_implemented("get_purchase_outstanding")

    def get_purchase_payment_status(self, purchase_id: int) -> PurchasePaymentStatus:
        self._not_implemented("get_purchase_payment_status")

    def get_purchase_financials(self, purchase_id: int) -> PurchaseFinancials:
        self._not_implemented("get_purchase_financials")

    def get_sale_outstanding(self, sale_id: int) -> None:
        self._not_implemented("get_sale_outstanding")

    def get_vendor_advance_balance(self, vendor_id: int) -> VendorBalance:
        self._not_implemented("get_vendor_advance_balance")

    def get_vendor_open_purchases(
        self, vendor_id: int
    ) -> tuple[VendorOpenPurchase, ...]:
        self._not_implemented("get_vendor_open_purchases")

    def get_vendor_statement(
        self,
        vendor_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> VendorStatement:
        self._not_implemented("get_vendor_statement")

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

    def record_vendor_payment_event(self, *args: Any, **kwargs: Any) -> None:
        self._not_implemented("record_vendor_payment_event")

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
