import builtins
from types import SimpleNamespace

from PySide6.QtWidgets import QFrame, QMessageBox, QWidget

from inventory_management.modules.purchase.controller import PurchaseController


def _toasts(widget):
    return widget.findChildren(QFrame, "notificationToast")


def test_fully_returned_purchase_uses_toast_not_blocking_information(qtbot, monkeypatch):
    view = QWidget()
    qtbot.addWidget(view)
    view.resize(500, 300)
    view.show()

    controller = PurchaseController.__new__(PurchaseController)
    controller.view = view
    controller.repo = SimpleNamespace(list_items=lambda _purchase_id: [])
    controller._selected_row_dict = lambda: {
        "purchase_id": "PO-1",
        "returned_value": 1.0,
        "calculated_total_amount": 0.0,
    }
    controller._returnable_map = lambda _purchase_id: {}
    controller._set_return_action_state = lambda *_args, **_kwargs: None

    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))

    controller._return()

    assert calls == []
    toast = _toasts(view)[0]
    assert toast.title_label.text() == "Return unavailable"
    assert toast.message_label.text() == "Purchase is fully returned."


def test_missing_weasyprint_uses_toast_not_blocking_information(qtbot, monkeypatch):
    view = QWidget()
    qtbot.addWidget(view)
    view.resize(500, 300)
    view.show()

    controller = PurchaseController.__new__(PurchaseController)
    controller.view = view

    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    controller._print_purchase_invoice("PO-1")

    assert calls == []
    toast = _toasts(view)[0]
    assert toast.title_label.text() == "WeasyPrint Not Available"
    assert toast.message_label.text() == "Please install WeasyPrint: pip install weasyprint"
