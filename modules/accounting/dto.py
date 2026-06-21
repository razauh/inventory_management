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
class PurchasePaymentStatus:
    purchase_id: int
    status: str
    paid_amount: Decimal
    applied_credit: Decimal
    remaining_due: Decimal


@dataclass(frozen=True)
class PurchaseFinancials:
    purchase_id: int
    net_total: Decimal
    paid_amount: Decimal
    applied_credit: Decimal
    returned_value: Decimal
    refunded_amount: Decimal
    outstanding: Decimal


@dataclass(frozen=True)
class VendorOpenPurchase:
    purchase_id: int
    vendor_id: int
    purchase_date: str | None
    reference: str | None
    net_total: Decimal
    outstanding: Decimal


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
    sale_id: int
    outstanding: Decimal


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
class JournalPreview:
    source_type: str
    source_id: int
    lines: tuple[Any, ...] = ()
