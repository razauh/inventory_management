from types import SimpleNamespace

from PySide6.QtWidgets import QPushButton

from inventory_management.modules.purchase.controller import PurchaseController


def test_purchase_payment_button_disabled_when_fully_paid(qtbot):
    controller = PurchaseController.__new__(PurchaseController)
    controller.view = SimpleNamespace(btn_pay=QPushButton("Payment"))
    qtbot.addWidget(controller.view.btn_pay)

    controller._set_payment_action_state({"remaining_due": 0.0})

    assert not controller.view.btn_pay.isEnabled()
    assert "fully settled" in controller.view.btn_pay.toolTip()


def test_purchase_payment_button_disabled_when_fully_returned(qtbot):
    controller = PurchaseController.__new__(PurchaseController)
    controller.view = SimpleNamespace(btn_pay=QPushButton("Payment"))
    qtbot.addWidget(controller.view.btn_pay)

    controller._set_payment_action_state(
        {"returned_value": 100.0, "calculated_total_amount": 0.0, "remaining_due": 10.0}
    )

    assert not controller.view.btn_pay.isEnabled()
    assert "fully returned" in controller.view.btn_pay.toolTip()


def test_purchase_payment_button_enabled_when_due(qtbot):
    controller = PurchaseController.__new__(PurchaseController)
    controller.view = SimpleNamespace(btn_pay=QPushButton("Payment"))
    qtbot.addWidget(controller.view.btn_pay)

    controller._set_payment_action_state({"remaining_due": 12.5})

    assert controller.view.btn_pay.isEnabled()
    assert "12.50" in controller.view.btn_pay.toolTip()
