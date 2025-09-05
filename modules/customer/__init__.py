# /home/pc/Desktop/inventory_management/modules/customer/__init__.py

from .actions import (
    ActionResult,
    receive_payment,
    record_advance,
    apply_advance,
    open_payment_history,
)
from .controller import CustomerController
from .details import CustomerDetails
from .form import CustomerForm
from .history import CustomerHistoryService, get_customer_history_service
from .model import CustomersTableModel
from .view import CustomerView

__all__ = [
    # actions
    "ActionResult",
    "receive_payment",
    "record_advance",
    "apply_advance",
    "open_payment_history",
    # widgets/controllers
    "CustomerController",
    "CustomerView",
    "CustomerDetails",
    "CustomerForm",
    "CustomersTableModel",
    # history service
    "CustomerHistoryService",
    "get_customer_history_service",
]
