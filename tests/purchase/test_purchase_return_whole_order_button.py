from inventory_management.modules.purchase.view import PurchaseView


def test_purchase_view_has_whole_order_return_button(qtbot):
    view = PurchaseView()
    qtbot.addWidget(view)

    assert view.btn_return_all.text() == "Return Whole Order"
