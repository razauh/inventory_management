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

    If with_ui=True (default), opens `payments/ui/customer_receipt_form.py`
    and expects a function `open_receipt_form(sale_id, customer_id, defaults) -> dict|None`
    that returns a mapping with keys compatible with `SalePaymentsRepo.record_payment`.

    Otherwise, it uses `form_defaults` directly.
    """
    # 1) Collect data (UI or provided)
    form_data: Optional[Dict[str, Any]] = None
    if with_ui:
        try:
            # Lazy import UI only when needed
            from payments.ui.customer_receipt_form import open_receipt_form  # type: ignore
        except ImportError:
            return ActionResult(
                success=False,
                message=(
                    "Receipt form UI is unavailable. "
                    "Either install `payments.ui.customer_receipt_form` or call with with_ui=False "
                    "and pass `form_defaults`."
                ),
            )
        form_data = open_receipt_form(sale_id=sale_id, customer_id=customer_id, defaults=form_defaults or {})
        if not form_data:
            return ActionResult(success=False, message="Payment cancelled by user.", payload=None)
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
    amount_to_apply: float,              # positive in UI; will be stored as negative
    date: Optional[str] = None,
    notes: Optional[str] = None,
    created_by: Optional[int] = None,
    repo_factory: Callable[[str | Path], Any] = _get_customer_advances_repo,
) -> ActionResult:
    """
    Apply customer credit to a sale. UI supplies a positive amount; we store negative.
    DB-level guard prevents over-application overall; repo checks remaining due for the sale.
    """
    if amount_to_apply is None or amount_to_apply <= 0:
        return ActionResult(success=False, message="Amount to apply must be > 0.")
    repo = repo_factory(db_path)
    try:
        tx_id = repo.apply_credit_to_sale(
            customer_id=customer_id,
            sale_id=sale_id,
            amount=-abs(float(amount_to_apply)),  # store negative
            date=date,
            notes=notes,
            created_by=created_by,
        )
        return ActionResult(success=True, id=tx_id, message="Advance applied to sale.")
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

    If with_ui=True, it expects `payments/ui/payment_history_view.py` with:
        `open_customer_history(customer_id: int, history: dict) -> None`
    """
    history_service = _get_customer_history_service(db_path)
    history_payload = history_service.full_history(customer_id)

    if not with_ui:
        return ActionResult(success=True, payload=history_payload)

    # Try to open the optional UI.
    try:
        from payments.ui.payment_history_view import open_customer_history  # type: ignore
    except ImportError:
        # No UI available — still succeed and return the payload for the caller/UI to use.
        return ActionResult(
            success=True,
            message=(
                "History view UI is unavailable; returning data payload only. "
                "Install `payments.ui.payment_history_view` to enable the window."
            ),
            payload=history_payload,
        )

    # Open the UI — any exceptions here should bubble up to help debugging
    open_customer_history(customer_id=customer_id, history=history_payload)
    return ActionResult(success=True, message="History view opened.", payload=None)
