"""Placeholder validators for future accounting boundaries."""

from __future__ import annotations

from typing import Any

from .exceptions import AccountingNotImplementedError


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
