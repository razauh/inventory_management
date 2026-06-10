# /home/pc/Desktop/inventory_management/modules/purchase/__init__.py

"""
Purchase module package exports.

When PySide6 is installed, all purchase UI/model/controller exports are
available. Without PySide6, exports are set to None so non-UI import checks can
still import this package.
"""


def _is_missing_qt_import(exc: ImportError) -> bool:
    name = getattr(exc, "name", "") or ""
    return name == "PySide6" or name.startswith("PySide6.") or "PySide6" in str(exc)


try:
    from .controller import PurchaseController  # type: ignore
    from .view import PurchaseView  # type: ignore
    from .model import PurchasesTableModel, PurchaseItemsModel  # type: ignore
    from .form import PurchaseForm  # type: ignore
    from .return_form import PurchaseReturnForm  # type: ignore
    from .details import PurchaseDetails  # type: ignore
    from .items import PurchaseItemsView  # type: ignore
    from .payment_form import PaymentForm  # type: ignore
except ImportError as exc:  # pragma: no cover
    if not _is_missing_qt_import(exc):
        raise
    PurchaseController = None  # type: ignore
    PurchaseView = None  # type: ignore
    PurchasesTableModel = None  # type: ignore
    PurchaseItemsModel = None  # type: ignore
    PurchaseForm = None  # type: ignore
    PurchaseReturnForm = None  # type: ignore
    PurchaseDetails = None  # type: ignore
    PurchaseItemsView = None  # type: ignore
    PaymentForm = None  # type: ignore

__all__ = [
    "PurchaseController",
    "PurchaseView",
    "PurchasesTableModel",
    "PurchaseItemsModel",
    "PurchaseForm",
    "PurchaseReturnForm",
    "PurchaseDetails",
    "PurchaseItemsView",
    "PaymentForm",
]
