from PySide6.QtCore import Qt

from inventory_management.modules.sales.model import SalesTableModel


def _sale_row(status, due):
    return {
        "sale_id": "SO-1",
        "date": "2026-06-20",
        "customer_name": "Customer",
        "total_amount": 100.0,
        "paid_amount": 100.0 - due,
        "remaining_due": due,
        "payment_status": status,
    }


def test_sales_due_and_status_cells_are_colored():
    model = SalesTableModel([_sale_row("partial", 25.0)])

    assert model.headerData(5, Qt.Horizontal, Qt.DisplayRole) == "Due"
    assert model.data(model.index(0, 5), Qt.BackgroundRole) is not None
    assert model.data(model.index(0, 6), Qt.BackgroundRole) is not None


def test_sales_fully_returned_row_is_colored():
    model = SalesTableModel(
        [_sale_row("paid", 0.0) | {"returned_value": 100.0, "returnable_lines": 0}]
    )

    assert model.data(model.index(0, 0), Qt.BackgroundRole) is not None
