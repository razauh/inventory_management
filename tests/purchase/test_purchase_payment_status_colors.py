from PySide6.QtCore import Qt

from inventory_management.modules.purchase.model import PurchasesTableModel


def _purchase_row(status, due):
    return {
        "purchase_id": "PO-1",
        "date": "2026-06-20",
        "vendor_name": "Vendor",
        "total_amount": 100.0,
        "returned_value": 0.0,
        "calculated_total_amount": 100.0,
        "paid_amount": 100.0 - due,
        "advance_payment_applied": 0.0,
        "remaining_due": due,
        "payment_status": status,
    }


def test_purchase_due_and_status_cells_are_colored():
    model = PurchasesTableModel([_purchase_row("paid", 0.0)])

    assert model.data(model.index(0, 7), Qt.BackgroundRole) is not None
    assert model.data(model.index(0, 8), Qt.BackgroundRole) is not None


def test_purchase_fully_returned_row_is_colored():
    model = PurchasesTableModel(
        [_purchase_row("paid", 0.0) | {"returned_value": 100.0, "calculated_total_amount": 0.0}]
    )

    assert model.data(model.index(0, 0), Qt.BackgroundRole) is not None
