from types import SimpleNamespace

from inventory_management.modules.customer import actions as customer_actions
from inventory_management.modules.customer import receipt_dialog
from inventory_management.modules.sales import controller as sales_controller


def _controller():
    controller = sales_controller.SalesController.__new__(sales_controller.SalesController)
    controller._doc_type = "sale"
    controller._db_path = "unused-test.db"
    controller.view = object()
    controller._selected_row = lambda: {"sale_id": "SO-1", "customer_id": 7}
    controller._eligible_sales_for_application = lambda customer_id: []
    controller._list_sales_for_customer = lambda customer_id: []
    controller._reload = lambda: None
    controller._sync_details = lambda: None
    controller._update_action_states = lambda: None
    return controller


def test_apply_credit_passes_amount_and_refreshes_after_success(monkeypatch):
    controller = _controller()
    calls = {"reload": 0, "sync": 0}
    messages = []

    monkeypatch.setattr(
        receipt_dialog,
        "open_payment_or_advance_form",
        lambda **kwargs: {"sale_id": "SO-1", "amount": 125.0},
    )

    def apply_customer_advance(**kwargs):
        assert kwargs["form_defaults"]["amount"] == 125.0
        assert "amount_to_apply" not in kwargs["form_defaults"]
        return SimpleNamespace(success=True, message="Advance applied to sale.")

    monkeypatch.setattr(customer_actions, "apply_customer_advance", apply_customer_advance)
    monkeypatch.setattr(sales_controller, "info", lambda view, title, text: messages.append((title, text)))
    controller._reload = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    controller._sync_details = lambda: calls.__setitem__("sync", calls["sync"] + 1)

    controller._on_apply_credit()

    assert messages == [("Saved", "Credit application recorded.")]
    assert calls == {"reload": 1, "sync": 1}


def test_apply_credit_does_not_report_success_or_refresh_on_action_failure(monkeypatch):
    controller = _controller()
    calls = {"reload": 0, "sync": 0}
    messages = []

    monkeypatch.setattr(
        receipt_dialog,
        "open_payment_or_advance_form",
        lambda **kwargs: {"sale_id": "SO-1", "amount": 125.0},
    )
    monkeypatch.setattr(
        customer_actions,
        "apply_customer_advance",
        lambda **kwargs: SimpleNamespace(success=False, message="Amount must be greater than zero."),
    )
    monkeypatch.setattr(sales_controller, "info", lambda view, title, text: messages.append((title, text)))
    controller._reload = lambda: calls.__setitem__("reload", calls["reload"] + 1)
    controller._sync_details = lambda: calls.__setitem__("sync", calls["sync"] + 1)

    controller._on_apply_credit()

    assert messages == [("Not saved", "Amount must be greater than zero.")]
    assert calls == {"reload": 0, "sync": 0}
