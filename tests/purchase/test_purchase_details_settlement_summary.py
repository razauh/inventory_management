from inventory_management.modules.purchase.details import PurchaseDetails


def test_purchase_details_shows_cash_credit_and_total_settled(qtbot):
    details = PurchaseDetails()
    qtbot.addWidget(details)

    details.set_data(
        {
            "purchase_id": "PO-001",
            "date": "2026-06-10",
            "vendor_name": "Vendor X",
            "total_amount": 500.0,
            "calculated_total_amount": 500.0,
            "returned_value": 0.0,
            "paid_amount": 125.0,
            "advance_payment_applied": 75.0,
            "payment_status": "partial",
        }
    )

    assert details.lab_paid.text() == "125.00"
    assert details.lab_credit_applied.text() == "75.00"
    assert details.lab_total_settled.text() == "200.00"
    assert details.lab_remain.text() == "300.00"


def test_purchase_details_settlement_summary_defaults_invalid_values(qtbot):
    details = PurchaseDetails()
    qtbot.addWidget(details)

    details.set_data(
        {
            "purchase_id": "PO-002",
            "date": "2026-06-10",
            "vendor_name": "Vendor X",
            "total_amount": 100.0,
            "paid_amount": "invalid",
            "advance_payment_applied": None,
            "payment_status": "unpaid",
        }
    )

    assert details.lab_paid.text() == "0.00"
    assert details.lab_credit_applied.text() == "0.00"
    assert details.lab_total_settled.text() == "0.00"
    assert details.lab_remain.text() == "100.00"
