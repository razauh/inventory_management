from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from inventory_management.modules.vendor.controller import VendorController


class TrackingConnection:
    def __init__(self):
        self.statements = []

    def execute(self, sql, parameters=()):
        self.statements.append((sql, parameters))
        return MagicMock()


def make_controller():
    controller = VendorController.__new__(VendorController)
    controller.conn = TrackingConnection()
    controller.repo = MagicMock()
    controller.vadv = MagicMock()
    controller.view = SimpleNamespace()
    controller._selected_id = MagicMock(return_value=7)
    controller._list_company_bank_accounts = MagicMock(return_value=[])
    controller._list_vendor_bank_accounts = MagicMock(return_value=[])
    controller._reload = MagicMock()
    return controller


def test_apply_advance_records_credit_once_after_dialog_accepts():
    payload = {
        "vendor_id": 7,
        "amount": 125.0,
        "date": "2026-06-09",
        "notes": "Advance",
    }
    controller = make_controller()
    controller.vadv.grant_credit.return_value = 42

    with (
        patch(
            "inventory_management.modules.vendor.payment_dialog.open_vendor_money_form",
            return_value=payload,
        ) as open_form,
        patch("inventory_management.modules.vendor.controller.info") as show_info,
    ):
        controller._on_apply_advance_dialog()

    defaults = open_form.call_args.kwargs["defaults"]
    assert "submit_advance" not in defaults
    controller.vadv.grant_credit.assert_called_once_with(
        vendor_id=7,
        amount=125.0,
        date="2026-06-09",
        notes="Advance",
        created_by=None,
        source_id=None,
        source_type="deposit",
    )
    assert [statement for statement, _ in controller.conn.statements] == [
        "SAVEPOINT apply_advance",
        "RELEASE apply_advance",
    ]
    controller._reload.assert_called_once_with()
    show_info.assert_called_once_with(
        controller.view,
        "Recorded",
        "Advance payment of 125.00 recorded successfully (Tx #42).",
    )


def test_apply_advance_rolls_back_when_credit_cannot_be_recorded():
    payload = {
        "vendor_id": 7,
        "amount": 125.0,
        "date": "2026-06-09",
        "notes": "Advance",
    }
    controller = make_controller()
    controller.vadv.grant_credit.side_effect = ValueError("credit rejected")

    with (
        patch(
            "inventory_management.modules.vendor.payment_dialog.open_vendor_money_form",
            return_value=payload,
        ),
        patch("inventory_management.modules.vendor.controller.info") as show_info,
    ):
        controller._on_apply_advance_dialog()

    controller.vadv.grant_credit.assert_called_once()
    assert [statement for statement, _ in controller.conn.statements] == [
        "SAVEPOINT apply_advance",
        "ROLLBACK TO apply_advance",
        "RELEASE apply_advance",
    ]
    controller._reload.assert_not_called()
    show_info.assert_called_once_with(
        controller.view,
        "Not recorded",
        "credit rejected",
    )
