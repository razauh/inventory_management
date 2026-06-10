from unittest.mock import MagicMock, patch

from inventory_management.database.repositories.vendor_bank_accounts_repo import VendorBankAccountsRepo
from inventory_management.modules.purchase.controller import PurchaseController
from inventory_management.modules.purchase.return_form import PurchaseReturnForm


class FakeVendorBankAccountsRepo:
    def __init__(self):
        self.calls = []

    def list(self, vendor_id, active_only=True):
        self.calls.append((vendor_id, active_only))
        return [
            {
                "vendor_bank_account_id": 101,
                "label": "Primary Refund Account",
                "is_primary": 1,
            },
            {
                "vendor_bank_account_id": 102,
                "label": "Secondary Refund Account",
                "is_primary": 0,
            },
        ]


def test_purchase_return_form_loads_saved_vendor_accounts_with_supported_repo_api(qtbot):
    repo = FakeVendorBankAccountsRepo()

    form = PurchaseReturnForm(
        None,
        items=[],
        vendor_id=7,
        vendor_bank_accounts_repo=repo,
    )
    qtbot.addWidget(form)

    assert repo.calls == [(7, True)]
    assert form.cmb_vendor_acct.itemText(0) == "Primary Refund Account"
    assert form.cmb_vendor_acct.itemData(0) == 101
    assert form.cmb_vendor_acct.itemText(1) == "Secondary Refund Account"
    assert form.cmb_vendor_acct.itemData(1) == 102
    assert form.cmb_vendor_acct.itemText(2) == "Temporary/External Bank Account"
    assert form.cmb_vendor_acct.itemData(2) == form.TEMP_BANK_KEY


def test_purchase_return_controller_passes_vendor_bank_repo_to_return_form(conn, current_user):
    controller = PurchaseController(conn, current_user)
    selected_row = {
        "purchase_id": "PO-RETURN-BANKS",
        "vendor_id": 7,
        "order_discount": 0.0,
    }
    purchase_item = {
        "item_id": 21,
        "product_id": 31,
        "uom_id": 41,
    }
    controller._selected_row_dict = MagicMock(return_value=selected_row)
    controller.repo.list_items = MagicMock(return_value=[purchase_item])
    controller._returnable_map = MagicMock(return_value={21: 1.0})

    with patch("inventory_management.modules.purchase.controller.PurchaseReturnForm") as mock_form:
        mock_form.return_value.exec.return_value = False

        controller._return()

    kwargs = mock_form.call_args.kwargs
    assert kwargs["vendor_id"] == 7
    assert isinstance(kwargs["vendor_bank_accounts_repo"], VendorBankAccountsRepo)
