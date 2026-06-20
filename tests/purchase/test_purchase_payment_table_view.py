from inventory_management.modules.purchase.view import PurchaseView


def test_purchase_view_shows_payments_table(qtbot):
    view = PurchaseView()
    qtbot.addWidget(view)

    assert hasattr(view, "payments")
    assert hasattr(view, "payments_tbl")
    assert view.tabs.tabText(1) == "Payments"

    view.payments.set_rows(
        [
            {
                "payment_id": 1,
                "date": "2026-06-20",
                "method": "cash",
                "amount": 25.0,
                "clearing_state": "cleared",
            }
        ]
    )

    assert view.payments.model.rowCount() == 1
