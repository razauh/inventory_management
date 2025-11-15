# /home/pc/Desktop/inventory_management/modules/customer/actions.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import sqlite3


@dataclass
class ActionResult:
    success: bool
    id: Optional[int] = None        # created tx/payment id (if any)
    message: Optional[str] = None   # user-facing message
    payload: Optional[dict] = None  # any extra data (echoed form, history, etc.)


# ------- dependency factories (DI-friendly) ---------------------------------

def _get_sale_payments_repo(db_path: str | Path):
    # Lazy import to keep UI/server startup fast
    from inventory_management.database.repositories.sale_payments_repo import (
        SalePaymentsRepo,
    )
    return SalePaymentsRepo(db_path)


def _get_customer_advances_repo(db_path: str | Path):
    from inventory_management.database.repositories.customer_advances_repo import (
        CustomerAdvancesRepo,
    )
    return CustomerAdvancesRepo(db_path)


def _get_customer_history_service(db_path: str | Path):
    from inventory_management.modules.customer.history import (
        CustomerHistoryService,
    )
    return CustomerHistoryService(db_path)


# ======================= Actions: Receive Payment ============================

def receive_payment(
    *,
    db_path: str | Path,
    sale_id: str,
    customer_id: int,
    created_by: Optional[int] = None,
    # If you already collected fields in your UI, pass them here and set with_ui=False
    form_defaults: Optional[Dict[str, Any]] = None,
    with_ui: bool = True,
    # DI overrides (useful for tests)
    repo_factory: Callable[[str | Path], Any] = _get_sale_payments_repo,
) -> ActionResult:
    """
    Receive a customer payment against a SALE (not a quotation).

    If with_ui=True (default), opens the local dialog:
        inventory_management.modules.customer.receipt_dialog.open_payment_or_advance_form(mode="receipt", ...)

    Otherwise (with_ui=False), uses `form_defaults` directly.
    """
    # 1) Collect data (UI or provided)
    form_data: Optional[Dict[str, Any]] = None
    if with_ui:
        # Prefer the new local dialog
        try:
            from inventory_management.modules.customer.receipt_dialog import (  # type: ignore
                open_payment_or_advance_form,
            )
        except ImportError:
            # Per update: do not fall back to legacy payments UI
            return ActionResult(
                success=False,
                message=(
                    "Receipt form UI is unavailable. Enable 'modules.customer.receipt_dialog' "
                    "or call with with_ui=False and pass `form_defaults`."
                ),
            )
        form_data = open_payment_or_advance_form(
            mode="receipt",
            customer_id=customer_id,
            sale_id=sale_id,
            defaults=form_defaults or {},
        )

        if not form_data:
            return ActionResult(success=False, payload=None)
    else:
        if not form_defaults:
            return ActionResult(success=False, message="Missing form_defaults while with_ui=False.")
        form_data = dict(form_defaults)

    # Ensure required fields exist; repo will perform deeper validation
    required = ("amount", "method")
    missing = [k for k in required if k not in form_data or form_data[k] is None]
    if missing:
        return ActionResult(success=False, message=f"Missing required fields: {', '.join(missing)}", payload=form_data)

    # 2) Persist via repo (soft validations mirror DB triggers)
    repo = repo_factory(db_path)
    try:
        payment_id = repo.record_payment(
            sale_id=sale_id,
            amount=float(form_data["amount"]),
            method=str(form_data["method"]),
            date=form_data.get("date"),
            bank_account_id=form_data.get("bank_account_id"),
            instrument_type=form_data.get("instrument_type"),
            instrument_no=form_data.get("instrument_no"),
            instrument_date=form_data.get("instrument_date"),
            deposited_date=form_data.get("deposited_date"),
            cleared_date=form_data.get("cleared_date"),
            clearing_state=form_data.get("clearing_state"),
            ref_no=form_data.get("ref_no"),
            notes=form_data.get("notes"),
            created_by=created_by or form_data.get("created_by"),
        )
        return ActionResult(success=True, id=payment_id, message="Payment recorded.", payload=form_data)
    except (ValueError, sqlite3.IntegrityError) as e:
        return ActionResult(success=False, message=str(e), payload=form_data)


# ======================= Actions: Advances (Credit) ==========================
# Existing non-UI actions (kept for backward compatibility)

def record_advance(
    *,
    db_path: str | Path,
    customer_id: int,
    amount: float,
    date: Optional[str] = None,   # 'YYYY-MM-DD'
    notes: Optional[str] = None,
    created_by: Optional[int] = None,
    repo_factory: Callable[[str | Path], Any] = _get_customer_advances_repo,
) -> ActionResult:
    """
    Record a customer deposit/advance (adds credit). amount must be > 0.
    """
    repo = repo_factory(db_path)
    try:
        tx_id = repo.grant_credit(
            customer_id=customer_id,
            amount=amount,
            date=date,
            notes=notes,
            created_by=created_by,
        )
        return ActionResult(success=True, id=tx_id, message="Advance recorded.")
    except (ValueError, sqlite3.IntegrityError) as e:
        return ActionResult(success=False, message=str(e))


def apply_advance(
    *,
    db_path: str | Path,
    customer_id: int,
    sale_id: str,
    amount_to_apply: float,              # positive in UI; repo writes negative
    date: Optional[str] = None,
    notes: Optional[str] = None,
    created_by: Optional[int] = None,
    repo_factory: Callable[[str | Path], Any] = _get_customer_advances_repo,
) -> ActionResult:
    """
    Apply customer credit to a sale.

    The UI supplies a positive amount; the repository (CustomerAdvancesRepo)
    validates against the sale's remaining due and records the application
    as a NEGATIVE amount in the ledger. Do not negate here.
    """
    if amount_to_apply is None or amount_to_apply <= 0:
        return ActionResult(success=False, message="Amount to apply must be > 0.")
    repo = repo_factory(db_path)
    try:
        tx_id = repo.apply_credit_to_sale(
            customer_id=customer_id,
            sale_id=sale_id,
            amount=float(amount_to_apply),   # pass positive; repo stores negative
            date=date,
            notes=notes,
            created_by=created_by,
        )
        return ActionResult(success=True, id=tx_id, message="Advance applied to sale.")
    except (ValueError, sqlite3.IntegrityError) as e:
        return ActionResult(success=False, message=str(e))


# ======================= NEW: UI-enabled Advance Helpers =====================

def record_customer_advance(
    *,
    db_path: str | Path,
    customer_id: int,
    # If you already collected fields in your UI, pass them here and set with_ui=False
    form_defaults: Optional[Dict[str, Any]] = None,
    with_ui: bool = True,
    repo_factory: Callable[[str | Path], Any] = _get_customer_advances_repo,
) -> ActionResult:
    """
    Record a customer advance via UI or direct payload.

    UI path (preferred):
        inventory_management.modules.customer.receipt_dialog.open_payment_or_advance_form(mode="advance", ...)

    Non-UI path:
        Uses `form_defaults` as payload to CustomerAdvancesRepo.grant_credit(...)
    """
    form_data: Optional[Dict[str, Any]] = None
    if with_ui:
        try:
            from inventory_management.modules.customer.receipt_dialog import (  # type: ignore
                open_payment_or_advance_form,
            )
        except ImportError:
            return ActionResult(
                success=False,
                message=(
                    "Advance form UI is unavailable. "
                    "Enable 'modules.customer.receipt_dialog' or call with with_ui=False and pass `form_defaults`."
                ),
            )
        form_data = open_payment_or_advance_form(
            mode="advance",
            customer_id=customer_id,
            sale_id=None,
            defaults=form_defaults or {},
        )
        if not form_data:
            return ActionResult(success=False, payload=None)
    else:
        if not form_defaults:
            return ActionResult(success=False, message="Missing form_defaults while with_ui=False.")
        form_data = dict(form_defaults)

    # required: amount (>0)
    if "amount" not in form_data or form_data["amount"] is None or float(form_data["amount"]) <= 0:
        return ActionResult(success=False, message="Amount must be greater than zero.", payload=form_data)

    repo = repo_factory(db_path)
    try:
        tx_id = repo.grant_credit(
            customer_id=customer_id,
            amount=float(form_data["amount"]),
            date=form_data.get("date"),
            notes=form_data.get("notes"),
            created_by=form_data.get("created_by"),
        )
        return ActionResult(success=True, id=tx_id, message="Advance recorded.", payload=form_data)
    except (ValueError, sqlite3.IntegrityError) as e:
        return ActionResult(success=False, message=str(e), payload=form_data)


def apply_customer_advance(
    *,
    db_path: str | Path,
    customer_id: int,
    sale_id: Optional[str] = None,           # may be chosen in UI if None
    # If you already collected fields in your UI, pass them here and set with_ui=False
    form_defaults: Optional[Dict[str, Any]] = None,
    with_ui: bool = True,
    repo_factory: Callable[[str | Path], Any] = _get_customer_advances_repo,
) -> ActionResult:
    """
    Apply an existing customer advance to a sale via UI or direct payload.

    UI path (preferred):
        inventory_management.modules.customer.receipt_dialog.open_payment_or_advance_form(mode="apply_advance", ...)

    Non-UI path:
        Uses `form_defaults` as payload to CustomerAdvancesRepo.apply_credit_to_sale(...)
    """
    form_data: Optional[Dict[str, Any]] = None
    if with_ui:
        try:
            from inventory_management.modules.customer.receipt_dialog import (  # type: ignore
                open_payment_or_advance_form,
            )
        except ImportError:
            return ActionResult(
                success=False,
                message=(
                    "Apply-advance UI is unavailable. "
                    "Enable 'modules.customer.receipt_dialog' or call with with_ui=False and pass `form_defaults`."
                ),
            )
        form_data = open_payment_or_advance_form(
            mode="apply_advance",
            customer_id=customer_id,
            sale_id=sale_id,
            defaults=form_defaults or {},
        )
        if not form_data:
            return ActionResult(success=False, payload=None)
    else:
        if not form_defaults:
            return ActionResult(success=False, message="Missing form_defaults while with_ui=False.")
        form_data = dict(form_defaults)

    # required: sale_id, amount (>0)
    sid = form_data.get("sale_id") or sale_id
    if not sid:
        return ActionResult(success=False, message="Missing sale_id for applying advance.", payload=form_data)
    if "amount" not in form_data or form_data["amount"] is None or float(form_data["amount"]) <= 0:
        return ActionResult(success=False, message="Amount must be greater than zero.", payload=form_data)

    repo = repo_factory(db_path)
    try:
        tx_id = repo.apply_credit_to_sale(
            customer_id=customer_id,
            sale_id=str(sid),
            amount=float(form_data["amount"]),   # positive; repo stores negative
            date=form_data.get("date"),
            notes=form_data.get("notes"),
            created_by=form_data.get("created_by"),
        )
        return ActionResult(success=True, id=tx_id, message="Advance applied to sale.", payload=form_data)
    except (ValueError, sqlite3.IntegrityError) as e:
        return ActionResult(success=False, message=str(e), payload=form_data)


# ======================= NEW: Payments Clearing Lifecycle ====================

def update_receipt_clearing(
    *,
    db_path: str | Path,
    payment_id: int,
    clearing_state: str,                 # 'posted' | 'pending' | 'cleared' | 'bounced'
    cleared_date: Optional[str] = None,  # 'YYYY-MM-DD' or None
    notes: Optional[str] = None,
    repo_factory: Callable[[str | Path], Any] = _get_sale_payments_repo,
) -> ActionResult:
    """
    Update the clearing lifecycle for an existing sale payment (receipt).
    """
    repo = repo_factory(db_path)
    try:
        updated = repo.update_clearing_state(
            payment_id=payment_id,
            clearing_state=clearing_state,
            cleared_date=cleared_date,
            notes=notes,
        )
        if updated <= 0:
            return ActionResult(success=False, message="No receipt updated.")
        return ActionResult(success=True, message="Receipt clearing updated.")
    except (ValueError, sqlite3.IntegrityError) as e:
        return ActionResult(success=False, message=str(e))


# ======================= Actions: History (Presenter) ========================

def open_payment_history(
    *,
    db_path: str | Path,
    customer_id: int,
    with_ui: bool = True,
) -> ActionResult:
    """
    Builds the customer's payment/credit history and (optionally) opens a UI view.

    If with_ui=True, it first tries local:
        inventory_management.modules.customer.payment_history_view.open_customer_history(...)

    After change: if local UI import fails, do NOT fall back to legacy — just return success with payload.
    """
    history_service = _get_customer_history_service(db_path)
    history_payload = history_service.full_history(customer_id)

    if not with_ui:
        return ActionResult(success=True, payload=history_payload)

    # Try to open the local UI first.
    try:
        from inventory_management.modules.customer.payment_history_view import (  # type: ignore
            open_customer_history,
        )
        open_customer_history(customer_id=customer_id, history=history_payload)
        return ActionResult(success=True, payload=None)
    except ImportError:
        # Per update: do not open legacy UI; return payload instead.
        return ActionResult(
            success=True,
            payload=history_payload,
        )
