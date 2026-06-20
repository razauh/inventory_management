from inventory_management.modules.sales.details import SaleDetails
from inventory_management.modules.sales.view import SalesView


def test_sale_details_shows_return_credit_amount(qtbot):
    details = SaleDetails()
    qtbot.addWidget(details)

    details.set_data(
        {
            "sale_id": "SO-001",
            "date": "2026-06-20",
            "customer_name": "Customer X",
            "gross_total_amount": 500.0,
            "order_discount": 0.0,
            "overall_discount": 0.0,
            "returned_qty": 1.0,
            "returned_value": 120.0,
            "net_total_amount": 380.0,
            "paid_amount": 500.0,
            "advance_payment_applied": 0.0,
            "return_credit_amount": 120.0,
            "remaining_due": 0.0,
            "payment_status": "paid",
            "doc_type": "sale",
        }
    )

    assert details.lab_return_credit.text() == "120.00"


def test_sales_view_has_whole_order_return_button(qtbot):
    view = SalesView()
    qtbot.addWidget(view)
    view.show()

    assert view.btn_return_all.text() == "Return Whole Order…"
    assert view.btn_return_all.isVisible()

    view.set_mode("quotation")

    assert not view.btn_return_all.isVisible()
