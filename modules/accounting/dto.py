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
    purchase_id: int
    outstanding: Decimal


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
