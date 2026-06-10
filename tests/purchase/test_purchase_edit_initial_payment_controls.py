from types import SimpleNamespace
from unittest.mock import patch

from inventory_management.modules.purchase.controller import PurchaseController
from inventory_management.modules.purchase.form import PurchaseForm


class _Vendors:
    def list_vendors(self):
        return [SimpleNamespace(vendor_id=7, name="Vendor")]


class _Products:
    def list_products(self):
        return []


def _purchase_form(qtbot, monkeypatch, allow_initial_payment=True):
    monkeypatch.setattr(PurchaseForm, "_reload_company_accounts", lambda self: None)
    monkeypatch.setattr(PurchaseForm, "_reload_vendor_accounts", lambda self: None)
    monkeypatch.setattr(PurchaseForm, "_update_vendor_advance_display", lambda self: None)

    form = PurchaseForm(
        vendors=_Vendors(),
        products=_Products(),
        initial={
            "vendor_id": 7,
            "date": "2026-06-10",
            "order_discount": 0.0,
            "notes": None,
            "items": [],
        },
        allow_initial_payment=allow_initial_payment,
    )
    qtbot.addWidget(form)
    return form


def test_create_form_keeps_initial_payment_controls_available(qtbot, monkeypatch):
    form = _purchase_form(qtbot, monkeypatch)

    assert not form.ip_box.isHidden()
    assert form.ip_box.isEnabled()


def test_edit_form_hides_and_ignores_initial_payment(qtbot, monkeypatch):
    form = _purchase_form(qtbot, monkeypatch, allow_initial_payment=False)

    assert form.ip_box.isHidden()
    assert not form.ip_box.isEnabled()

    form.ip_amount.setText("125")
    payload = form.get_payload()

    assert "initial_payment" not in payload


def test_edit_controller_opens_form_without_initial_payment_controls():
    controller = PurchaseController.__new__(PurchaseController)
    controller.view = object()
    controller.vendors = object()
    controller.products = object()
    controller.repo = SimpleNamespace(
        list_items=lambda _purchase_id: [],
        has_vendor_locking_activity=lambda _purchase_id: False,
    )
    controller._selected_row_dict = lambda: {
        "purchase_id": "PO-EDIT",
        "vendor_id": 7,
        "date": "2026-06-10",
        "order_discount": 0.0,
        "notes": None,
        "payment_status": "unpaid",
        "paid_amount": 0.0,
        "advance_payment_applied": 0.0,
    }

    with patch(
        "inventory_management.modules.purchase.controller.PurchaseForm"
    ) as form_class:
        form_class.return_value.exec.return_value = False

        controller._edit()

    assert form_class.call_args.kwargs["allow_initial_payment"] is False
