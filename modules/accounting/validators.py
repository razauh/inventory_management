"""Accounting boundary validators."""

from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from .current_rules.bank_rules import (
    validate_company_bank_account_active,
    validate_vendor_bank_account,
)
from .dto import SupplierRefundMetadata, VendorPaymentMetadata
from .exceptions import AccountingNotImplementedError


METHODS = {"Cash", "Bank Transfer", "Cheque", "Cross Cheque", "Cash Deposit", "Other"}
INSTRUMENT_TYPES = {"online", "cheque", "cross_cheque", "cash_deposit", "pay_order", "other"}


def validate_vendor_payment_metadata(
    conn: Connection,
    metadata: VendorPaymentMetadata,
) -> None:
    if metadata.method is not None and metadata.method not in METHODS:
        raise ValueError(f"Invalid vendor {metadata.vendor_label} payment method: {metadata.method}")
    if metadata.reject_card and metadata.method == "Card":
        raise ValueError("Card is not a supported vendor payment method")
    if (
        metadata.instrument_type is not None
        and metadata.instrument_type not in INSTRUMENT_TYPES
    ):
        raise ValueError(
            f"Invalid vendor {metadata.vendor_label} instrument type: {metadata.instrument_type}"
        )
    if metadata.clearing_state is not None and metadata.clearing_state != "cleared":
        if metadata.vendor_label == "purchase":
            raise ValueError("Vendor purchase payments must have clearing_state='cleared'")
        raise ValueError("Vendor outgoing payments must have clearing_state='cleared'")

    validate_company_bank_account_active(conn, metadata.bank_account_id)
    validate_vendor_bank_account(
        conn,
        vendor_id=metadata.vendor_id,
        vendor_bank_account_id=metadata.vendor_bank_account_id,
        vendor_label=metadata.vendor_label,
    )
    if metadata.require_method_details:
        _validate_method_requirements(metadata)


def validate_supplier_refund_metadata(
    conn: Connection,
    metadata: SupplierRefundMetadata,
) -> None:
    validate_vendor_payment_metadata(conn, metadata)


def _validate_method_requirements(metadata: VendorPaymentMetadata) -> None:
    method = metadata.method
    instrument_no = (metadata.instrument_no or "").strip()
    temp_name = (metadata.temp_vendor_bank_name or "").strip()
    temp_number = (metadata.temp_vendor_bank_number or "").strip()
    has_vendor_destination = bool(metadata.vendor_bank_account_id) or (
        bool(temp_name) and bool(temp_number)
    )

    if method == "Bank Transfer":
        if (
            metadata.bank_account_id is None
            or not instrument_no
            or (metadata.instrument_type is not None and metadata.instrument_type != "online")
            or not has_vendor_destination
        ):
            raise ValueError(
                "Bank Transfer requires company account, transaction #, "
                "instrument_type=online; vendor account or complete temporary account "
                "required for outgoing"
            )
    elif method == "Cheque":
        if (
            metadata.bank_account_id is None
            or not instrument_no
            or (metadata.instrument_type is not None and metadata.instrument_type != "cheque")
        ):
            raise ValueError(
                "Cheque requires company account, cheque #, instrument_type=cheque; "
                "vendor account not required"
            )
    elif method == "Cross Cheque":
        if (
            metadata.bank_account_id is None
            or not instrument_no
            or (
                metadata.instrument_type is not None
                and metadata.instrument_type != "cross_cheque"
            )
            or not has_vendor_destination
        ):
            raise ValueError(
                "Cross Cheque requires company account, cheque #, "
                "instrument_type=cross_cheque; vendor account or complete temporary "
                "account required for outgoing"
            )
    elif method == "Cash Deposit":
        if (
            not instrument_no
            or (
                metadata.instrument_type is not None
                and metadata.instrument_type != "cash_deposit"
            )
            or not has_vendor_destination
        ):
            raise ValueError(
                "Cash Deposit requires deposit slip #, instrument_type=cash_deposit; "
                "vendor account or complete temporary account required for outgoing"
            )
    elif method == "Cash":
        if metadata.bank_account_id is not None or (
            metadata.instrument_type is not None and metadata.instrument_type != "other"
        ):
            raise ValueError("Cash payment cannot reference bank account metadata")


def _not_implemented(name: str) -> None:
    raise AccountingNotImplementedError(
        f"Accounting validator is not implemented yet: {name}"
    )


def validate_non_negative_amount(amount: Any) -> None:
    _not_implemented("validate_non_negative_amount")


def validate_party_type(party_type: str) -> None:
    _not_implemented("validate_party_type")


def validate_accounting_event_type(event_type: str) -> None:
    _not_implemented("validate_accounting_event_type")


def validate_balanced_journal_preview(preview: Any) -> None:
    _not_implemented("validate_balanced_journal_preview")
