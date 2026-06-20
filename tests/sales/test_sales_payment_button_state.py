from inventory_management.modules.sales.controller import SalesController
from inventory_management.modules.sales.view import SalesView


def test_sales_payment_button_starts_disabled(qtbot):
    view = SalesView()
    qtbot.addWidget(view)

    assert not view.btn_record_payment.isEnabled()


def test_sales_payment_action_disabled_when_fully_paid():
    controller = SalesController.__new__(SalesController)
    controller._doc_type = "sale"

    payment_allowed, payment_message, credit_allowed, credit_message = (
        controller._financial_action_from_detail({"remaining_due": 0.0})
    )

    assert not payment_allowed
    assert "fully settled" in payment_message
    assert not credit_allowed
    assert "fully settled" in credit_message


def test_sales_payment_action_disabled_when_fully_returned():
    controller = SalesController.__new__(SalesController)
    controller._doc_type = "sale"

    payment_allowed, payment_message, credit_allowed, credit_message = (
        controller._financial_action_from_detail(
            {"remaining_due": 10.0, "returned_value": 100.0, "returnable_lines": 0}
        )
    )

    assert not payment_allowed
    assert "fully returned" in payment_message
    assert not credit_allowed
    assert "fully returned" in credit_message
