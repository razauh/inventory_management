import pytest

from inventory_management.modules.purchase.return_form import PurchaseReturnForm


class FakePurchasesRepo:
    def __init__(self, financials):
        self.financials = financials

    def fetch_purchase_financials(self, purchase_id):
        return self.financials


def _form(qtbot, financials):
    form = PurchaseReturnForm(
        None,
        items=[
            {
                "item_id": 1,
                "product_name": "Display Product",
                "unit_name": "Piece",
                "quantity": 10,
                "purchase_price": 10,
                "item_discount": 0,
                "returnable": 10,
            }
        ],
        vendor_id=1,
        purchases_repo=FakePurchasesRepo(financials),
    )
    qtbot.addWidget(form)
    form.set_purchase_id("PO-DISPLAY")
    return form


@pytest.mark.parametrize(
    ("return_qty", "expected_text"),
    [
        ("3", "Adjusted Payable: 20.00 (Original: 50.00)"),
        ("8", "Adjusted Payable: 0.00 (Original: 50.00) | Refund/Credit Due: 30.00"),
    ],
)
def test_purchase_return_remaining_display_clamps_payable_and_shows_excess(
    qtbot, return_qty, expected_text
):
    form = _form(
        qtbot,
        {
            "calculated_total_amount": 100.0,
            "paid_amount": 50.0,
            "advance_payment_applied": 0.0,
            "is_fully_paid": False,
            "remaining_refundable_amount": 50.0,
        },
    )

    form.tbl.item(0, form.COL_QTY_RETURN).setText(return_qty)
    form._update_remaining_amount()

    assert form.lbl_remaining.text() == expected_text
