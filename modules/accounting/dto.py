"""Small data objects for future accounting service boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class VendorBalance:
    vendor_id: int
    balance: Decimal


@dataclass(frozen=True)
class CustomerBalance:
    customer_id: int
    balance: Decimal


@dataclass(frozen=True)
class PurchaseOutstanding:
    purchase_id: int | str
    outstanding: Decimal


@dataclass(frozen=True)
class PurchaseTotals:
    purchase_id: int | str | None
    subtotal_before_order_discount: Decimal
    order_discount: Decimal
    returned_value: Decimal
    net_total: Decimal
    stored_total: Decimal | None = None


@dataclass(frozen=True)
class PurchaseTotalInputLine:
    quantity: Decimal
    purchase_price: Decimal
    item_discount: Decimal = Decimal("0")


@dataclass(frozen=True)
class PurchaseReturnPreviewLine:
    quantity: Decimal
    purchase_price: Decimal
    item_discount: Decimal = Decimal("0")
    return_qty: Decimal = Decimal("0")


@dataclass(frozen=True)
class PurchaseReturnPreviewPayload:
    lines: tuple[PurchaseReturnPreviewLine, ...]
    order_discount: Decimal = Decimal("0")


@dataclass(frozen=True)
class PurchaseReturnEffect:
    value_factor: Decimal
    total_qty: Decimal
    total_value: Decimal
    line_values: tuple[Decimal, ...] = ()


@dataclass(frozen=True)
class PurchaseReturnValue:
    transaction_id: int
    item_id: int | None
    qty_returned: Decimal
    unit_buy_price: Decimal
    unit_discount: Decimal
    return_date: str | None
    valuation_status: str
    return_value: Decimal


@dataclass(frozen=True)
class PurchaseReturnTotals:
    qty: Decimal
    value: Decimal


@dataclass(frozen=True)
class PurchaseReturnPayload:
    purchase_id: int | str
    date: str
    created_by: int | None
    lines: tuple[dict, ...]
    notes: str | None = None
    settlement: dict | None = None


@dataclass(frozen=True)
class PurchaseReturnResult:
    purchase_id: int | str
    transaction_ids: tuple[int, ...]
    return_value: Decimal
    settlement_amount: Decimal


@dataclass(frozen=True)
class PurchaseInventoryLine:
    item_id: int
    product_id: int
    quantity: Decimal
    uom_id: int


@dataclass(frozen=True)
class PurchaseInventoryPayload:
    purchase_id: int | str
    date: str | None
    created_by: int | None
    lines: tuple[PurchaseInventoryLine, ...] = ()
    notes: str | None = None
    replace_existing: bool = False
    delete_transaction_types: tuple[str, ...] | None = ("purchase",)


@dataclass(frozen=True)
class PurchaseInventoryResult:
    purchase_id: int | str
    transaction_ids: tuple[int, ...]


@dataclass(frozen=True)
class PurchaseReturnInventoryPayload:
    purchase_id: int | str
    date: str
    created_by: int | None
    lines: tuple[dict, ...]
    notes: str | None = None


@dataclass(frozen=True)
class PurchaseReturnInventoryResult:
    purchase_id: int | str
    transaction_ids: tuple[int, ...]


@dataclass(frozen=True)
class InventoryAccountingEvent:
    transaction_id: int
    product_id: int
    quantity: Decimal
    uom_id: int | None
    transaction_type: str
    source_type: str | None
    source_id: int | str | None
    source_item_id: int | None
    date: str | None
    txn_seq: int | None
    notes: str | None = None
    created_by: int | None = None


@dataclass(frozen=True)
class PurchaseInvoiceFinancials:
    purchase_id: int | str
    context: dict[str, Any]
    preview_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PurchaseReportBundle:
    rows_by_key: dict[str, tuple[dict[str, Any], ...]]


@dataclass(frozen=True)
class VendorAgingReport:
    as_of: str
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CustomerAgingReport:
    as_of: str
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class SalesDashboardMetrics:
    as_of: str
    total_sales: Decimal
    total_cogs: Decimal
    total_expenses: Decimal
    receipts_cleared: Decimal
    vendor_payments_cleared: Decimal
    open_receivables: Decimal
    open_payables: Decimal


@dataclass(frozen=True)
class APSummary:
    cutoff_date: str | None
    ar_total_due: Decimal
    ap_total_due: Decimal


@dataclass(frozen=True)
class PaymentActivityReport:
    start_date: str | None
    end_date: str | None
    collections: tuple[dict[str, Any], ...]
    disbursements: tuple[dict[str, Any], ...]
    total_collections: Decimal
    total_disbursements: Decimal
    summary_by_status: tuple[dict[str, Any], ...] = ()
    unprocessed: tuple[dict[str, Any], ...] = ()
    detailed: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class PurchasePaymentStatus:
    purchase_id: int | str
    status: str
    paid_amount: Decimal
    applied_credit: Decimal
    remaining_due: Decimal


@dataclass(frozen=True)
class PurchasePaymentRow:
    payment_id: int
    purchase_id: int | str
    date: str | None
    amount: Decimal
    method: str | None
    bank_account_id: int | None = None
    vendor_bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    instrument_date: str | None = None
    deposited_date: str | None = None
    cleared_date: str | None = None
    clearing_state: str | None = None
    ref_no: str | None = None
    notes: str | None = None
    created_by: int | None = None
    bank_account_label: str | None = None
    vendor_bank_account_label: str | None = None


@dataclass(frozen=True)
class PurchasePaymentSummary:
    purchase_id: int | str
    latest_payment: PurchasePaymentRow | None
    paid_amount: Decimal
    applied_credit: Decimal
    remaining_due: Decimal
    status: str
    overpayment_credited: Decimal
    counterparty_label: str = "Vendor"

    def to_detail_payload(self) -> dict | None:
        if self.latest_payment is None:
            return None
        return {
            "method": self.latest_payment.method,
            "amount": float(self.latest_payment.amount),
            "status": self.latest_payment.clearing_state or "posted",
            "overpayment": float(self.overpayment_credited),
            "counterparty_label": self.counterparty_label,
        }


@dataclass(frozen=True)
class VendorPaymentMetadata:
    vendor_id: int
    method: str | None
    bank_account_id: int | None = None
    vendor_bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    clearing_state: str | None = None
    temp_vendor_bank_name: str | None = None
    temp_vendor_bank_number: str | None = None
    vendor_label: str = "purchase"
    require_method_details: bool = False
    reject_card: bool = False


@dataclass(frozen=True)
class SupplierRefundMetadata(VendorPaymentMetadata):
    pass


@dataclass(frozen=True)
class SupplierRefundPayload:
    purchase_id: int | str
    vendor_id: int
    amount: Decimal
    date: str
    method: str
    bank_account_id: int | None = None
    vendor_bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    instrument_date: str | None = None
    deposited_date: str | None = None
    cleared_date: str | None = None
    clearing_state: str = "cleared"
    ref_no: str | None = None
    temp_vendor_bank_name: str | None = None
    temp_vendor_bank_number: str | None = None
    notes: str | None = None
    created_by: int | None = None


@dataclass(frozen=True)
class SupplierRefundResult:
    refund_id: int
    purchase_id: int | str
    vendor_id: int
    amount: Decimal


@dataclass(frozen=True)
class SupplierRefundRow:
    refund_id: int
    purchase_id: int | str
    vendor_id: int
    date: str
    amount: Decimal
    method: str
    bank_account_id: int | None = None
    vendor_bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    instrument_date: str | None = None
    deposited_date: str | None = None
    cleared_date: str | None = None
    clearing_state: str = "cleared"
    ref_no: str | None = None
    temp_vendor_bank_name: str | None = None
    temp_vendor_bank_number: str | None = None
    notes: str | None = None
    created_by: int | None = None


@dataclass(frozen=True)
class VendorCashMovement:
    date: str
    type: str
    amount: Decimal
    direction: str
    method: str | None
    status: str | None
    doc_id: int | str | None
    notes: str | None = None


@dataclass(frozen=True)
class BankLedgerRow:
    src: str
    payment_id: int
    date: str | None
    amount_in: Decimal
    amount_out: Decimal
    method: str | None
    instrument_type: str | None
    instrument_no: str | None
    bank_account_id: int | None
    doc_id: int | str | None
    vendor_bank_account_id: int | None = None


@dataclass(frozen=True)
class VendorPaymentPayload:
    purchase_id: int | str
    amount: Decimal
    method: str
    date: str
    bank_account_id: int | None = None
    vendor_bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    instrument_date: str | None = None
    deposited_date: str | None = None
    cleared_date: str | None = None
    clearing_state: str | None = None
    ref_no: str | None = None
    notes: str | None = None
    created_by: int | None = None
    temp_vendor_bank_name: str | None = None
    temp_vendor_bank_number: str | None = None


@dataclass(frozen=True)
class VendorPaymentEffect:
    purchase_id: int | str
    vendor_id: int
    amount_due: Decimal
    payment_amount: Decimal
    overpayment_credit: Decimal


@dataclass(frozen=True)
class VendorPaymentResult:
    payment_id: int | None
    credit_tx_id: int | None
    effect: VendorPaymentEffect


@dataclass(frozen=True)
class VendorAdvancePayload:
    vendor_id: int
    amount: Decimal
    date: str
    notes: str | None = None
    created_by: int | None = None
    source_id: int | str | None = None
    source_type: str = "deposit"
    method: str | None = None
    bank_account_id: int | None = None
    vendor_bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    instrument_date: str | None = None
    deposited_date: str | None = None
    cleared_date: str | None = None
    clearing_state: str | None = None
    ref_no: str | None = None
    temp_vendor_bank_name: str | None = None
    temp_vendor_bank_number: str | None = None


@dataclass(frozen=True)
class VendorAdvanceResult:
    tx_id: int
    vendor_id: int
    amount: Decimal
    source_type: str


@dataclass(frozen=True)
class VendorCreditLedgerRow:
    tx_id: int
    vendor_id: int
    tx_date: str | None
    amount: Decimal
    source_type: str
    source_id: str | None
    notes: str | None = None


@dataclass(frozen=True)
class PurchaseFinancials:
    purchase_id: int | str
    net_total: Decimal
    paid_amount: Decimal
    applied_credit: Decimal
    returned_value: Decimal
    refunded_amount: Decimal
    outstanding: Decimal
    total_amount: Decimal = Decimal("0")
    return_credit_amount: Decimal = Decimal("0")
    is_fully_paid: bool = False
    remaining_refundable_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class VendorPurchaseTotals:
    vendor_id: int
    purchases_total: Decimal
    paid_total: Decimal
    advance_applied_total: Decimal


@dataclass(frozen=True)
class VendorOpenPurchase:
    purchase_id: int | str
    vendor_id: int
    purchase_date: str | None
    reference: str | None
    net_total: Decimal
    outstanding: Decimal
    total_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    advance_payment_applied: Decimal = Decimal("0")
    calculated_total_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class VendorStatementEntry:
    entry_date: str | None
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass(frozen=True)
class VendorStatement:
    vendor_id: int
    start_date: str | None
    end_date: str | None
    opening_balance: Decimal
    closing_balance: Decimal
    entries: tuple[VendorStatementEntry, ...] = ()


@dataclass(frozen=True)
class SaleOutstanding:
    sale_id: int | str
    outstanding: Decimal


@dataclass(frozen=True)
class SaleTotalInputLine:
    quantity: Decimal
    unit_price: Decimal
    item_discount: Decimal = Decimal("0")


@dataclass(frozen=True)
class SaleTotals:
    sale_id: int | str | None
    subtotal_before_order_discount: Decimal
    order_discount: Decimal
    returned_value: Decimal
    net_total: Decimal
    stored_total: Decimal | None = None


@dataclass(frozen=True)
class SaleFinancialSummary:
    sale_id: int | str
    gross_total_amount: Decimal
    net_total: Decimal
    paid_amount: Decimal
    applied_credit: Decimal
    returned_value: Decimal
    outstanding: Decimal
    total_amount: Decimal = Decimal("0")
    return_credit_amount: Decimal = Decimal("0")
    is_fully_paid: bool = False
    remaining_refundable_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class SalePaymentStatus:
    sale_id: int | str
    status: str
    paid_amount: Decimal
    applied_credit: Decimal
    remaining_due: Decimal


@dataclass(frozen=True)
class SalePaymentRow:
    payment_id: int
    sale_id: int | str
    date: str | None
    amount: Decimal
    method: str | None
    bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    instrument_date: str | None = None
    deposited_date: str | None = None
    cleared_date: str | None = None
    clearing_state: str | None = None
    ref_no: str | None = None
    notes: str | None = None
    created_by: int | None = None
    bank_account_label: str | None = None


@dataclass(frozen=True)
class CustomerOpenSale:
    sale_id: int | str
    customer_id: int
    sale_date: str | None
    reference: str | None
    net_total: Decimal
    outstanding: Decimal
    total_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    calculated_total_amount: Decimal = Decimal("0")


@dataclass(frozen=True)
class CustomerStatementEntry:
    entry_date: str | None
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass(frozen=True)
class CustomerReceivableSummary:
    customer_id: int
    credit_balance: Decimal
    sales_count: int
    open_due_sum: Decimal
    last_sale_date: str | None = None
    last_payment_date: str | None = None
    last_advance_date: str | None = None


@dataclass(frozen=True)
class CustomerStatement:
    customer_id: int
    start_date: str | None
    end_date: str | None
    opening_balance: Decimal
    closing_balance: Decimal
    entries: tuple[CustomerStatementEntry, ...] = ()


@dataclass(frozen=True)
class SaleInvoiceFinancials:
    sale_id: int | str
    context: dict[str, Any]
    preview_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuotationFinancials:
    quotation_id: int | str
    context: dict[str, Any]
    preview_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PartyLedgerSummary:
    party_type: str
    party_id: int
    balance: Decimal


@dataclass(frozen=True)
class AccountingEvent:
    event_type: str
    source_type: str
    source_id: int
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CustomerPaymentPayload:
    sale_id: str
    customer_id: int
    amount: Decimal
    method: str
    date: str | None = None
    bank_account_id: int | None = None
    instrument_type: str | None = None
    instrument_no: str | None = None
    instrument_date: str | None = None
    deposited_date: str | None = None
    cleared_date: str | None = None
    clearing_state: str = "posted"
    ref_no: str | None = None
    notes: str | None = None
    created_by: int | None = None


@dataclass(frozen=True)
class CustomerPaymentEffect:
    sale_id: str
    customer_id: int
    amount: Decimal
    clearing_state: str


@dataclass(frozen=True)
class CustomerCreditPayload:
    customer_id: int
    amount: Decimal
    source_type: str = "deposit"
    source_id: str | None = None
    date: str | None = None
    method: str | None = None
    bank_account_id: int | None = None
    reference_no: str | None = None
    notes: str | None = None
    created_by: int | None = None


@dataclass(frozen=True)
class CustomerCreditResult:
    tx_id: int
    customer_id: int
    amount: Decimal
    source_type: str


@dataclass(frozen=True)
class CustomerCreditApplicationPayload:
    customer_id: int
    sale_id: str
    amount: Decimal
    date: str | None = None
    notes: str | None = None
    created_by: int | None = None


@dataclass(frozen=True)
class CustomerCreditApplicationResult:
    tx_id: int
    customer_id: int
    sale_id: str
    amount: Decimal


@dataclass(frozen=True)
class CustomerCreditLedgerRow:
    tx_id: int
    customer_id: int
    tx_date: str | None
    amount: Decimal
    source_type: str
    source_id: str | None = None
    method: str | None = None
    bank_account_id: int | None = None
    reference_no: str | None = None
    notes: str | None = None
    created_by: int | None = None


@dataclass(frozen=True)
class CustomerPaymentResult:
    payment_id: int
    effect: CustomerPaymentEffect


@dataclass(frozen=True)
class JournalPreview:
    source_type: str
    source_id: int
    lines: tuple[Any, ...] = ()
