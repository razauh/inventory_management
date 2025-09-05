# /home/pc/Desktop/inventory_management/modules/purchase/__init__.py

"""
Purchase module package exports.

Always available:
- PurchaseController

Optional UI/model components (imported defensively so environments
without Qt can still import this package):
- PurchaseView
- PurchasesTableModel
- PurchaseItemsModel
- PurchaseForm
- PurchaseReturnForm
- PurchasePaymentDialog
- PurchaseDetails
- PurchaseItemForm
- PurchaseItemsView
"""

from .controller import PurchaseController

# UI/model pieces are optional to avoid a hard Qt dependency during headless tests
try:
    from .view import PurchaseView  # type: ignore
    from .model import PurchasesTableModel, PurchaseItemsModel  # type: ignore
    from .form import PurchaseForm  # type: ignore
    from .return_form import PurchaseReturnForm  # type: ignore
    from .payments import PurchasePaymentDialog  # type: ignore
    from .details import PurchaseDetails  # type: ignore
    from .item_form import PurchaseItemForm  # type: ignore
    from .items import PurchaseItemsView  # type: ignore
except Exception:  # pragma: no cover
    PurchaseView = None  # type: ignore
    PurchasesTableModel = None  # type: ignore
    PurchaseItemsModel = None  # type: ignore
    PurchaseForm = None  # type: ignore
    PurchaseReturnForm = None  # type: ignore
    PurchasePaymentDialog = None  # type: ignore
    PurchaseDetails = None  # type: ignore
    PurchaseItemForm = None  # type: ignore
    PurchaseItemsView = None  # type: ignore

__all__ = [
    "PurchaseController",
    "PurchaseView",
    "PurchasesTableModel",
    "PurchaseItemsModel",
    "PurchaseForm",
    "PurchaseReturnForm",
    "PurchasePaymentDialog",
    "PurchaseDetails",
    "PurchaseItemForm",
    "PurchaseItemsView",
]
