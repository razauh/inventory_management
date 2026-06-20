from types import SimpleNamespace

from PySide6.QtWidgets import QPushButton

from inventory_management.modules.purchase.controller import PurchaseController


def test_purchase_return_buttons_disabled_when_fully_returned(qtbot):
    controller = PurchaseController.__new__(PurchaseController)
    controller.view = SimpleNamespace(
        btn_return=QPushButton("Return"),
        btn_return_all=QPushButton("Return Whole Order"),
    )
    qtbot.addWidget(controller.view.btn_return)
    qtbot.addWidget(controller.view.btn_return_all)

    controller._set_return_action_state(
        {"returned_value": 100.0, "calculated_total_amount": 0.0}
    )

    assert not controller.view.btn_return.isEnabled()
    assert not controller.view.btn_return_all.isEnabled()
    assert "fully returned" in controller.view.btn_return.toolTip()
