# /home/pc/Desktop/inventory_management/modules/sales/__init__.py

"""
Sales module package exports.

Always available:
- SalesController

Optional UI/model components (imported defensively so environments
without Qt can still import this package):
- SalesView
- PaymentsView
- PaymentsTableModel
- SalesTableModel
- SaleItemsModel
- SaleForm
- SaleReturnForm
- SaleDetails
- SaleItemsView
"""

import logging

from .controller import SalesController


_log = logging.getLogger(__name__)

# UI/model pieces are optional to avoid a hard Qt dependency during headless tests
try:
    from .view import SalesView, PaymentsView, PaymentsTableModel  # type: ignore
    from .model import SalesTableModel, SaleItemsModel  # type: ignore
    from .form import SaleForm  # type: ignore
    from .return_form import SaleReturnForm  # type: ignore
    from .details import SaleDetails  # type: ignore
    from .items import SaleItemsView  # type: ignore
except ImportError as exc:  # pragma: no cover
    _log.debug("Optional sales UI components are unavailable: %s", exc)
    SalesView = None  # type: ignore
    PaymentsView = None  # type: ignore
    PaymentsTableModel = None  # type: ignore
    SalesTableModel = None  # type: ignore
    SaleItemsModel = None  # type: ignore
    SaleForm = None  # type: ignore
    SaleReturnForm = None  # type: ignore
    SaleDetails = None  # type: ignore
    SaleItemsView = None  # type: ignore
except Exception:  # pragma: no cover
    _log.exception("Unexpected error importing optional sales UI components")
    SalesView = None  # type: ignore
    PaymentsView = None  # type: ignore
    PaymentsTableModel = None  # type: ignore
    SalesTableModel = None  # type: ignore
    SaleItemsModel = None  # type: ignore
    SaleForm = None  # type: ignore
    SaleReturnForm = None  # type: ignore
    SaleDetails = None  # type: ignore
    SaleItemsView = None  # type: ignore

__all__ = [
    "SalesController",
    "SalesView",
    "PaymentsView",
    "PaymentsTableModel",
    "SalesTableModel",
    "SaleItemsModel",
    "SaleForm",
    "SaleReturnForm",
    "SaleDetails",
    "SaleItemsView",
]
