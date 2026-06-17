from types import SimpleNamespace

from inventory_management.modules.customer import actions as customer_actions
from inventory_management.modules.customer import receipt_dialog
from inventory_management.modules.sales import controller as sales_controller


def _controller():
    controller = sales_controller.SalesController.__new__(sales_controller.SalesController)
    controller._doc_type = "sale"
    controller._db_path = "unused-test.db"
    controller.conn = None
    controller.view = object()
    controller._selected_row = lambda: {"sale_id": "SO-1", "customer_id": 7}
    controller._fetch_sale_financials = lambda sale_id: {"remaining_due": 500.0}
    controller._eligible_sales_for_application = lambda customer_id: []
    controller._list_sales_for_customer = lambda customer_id: []
    controller._reload = lambda: None
    controller._sync_details = lambda: None
    controller._update_action_states = lambda: None
    return controller


def test_apply_credit_passes_amount_and_refreshes_after_success(monkeypatch):
    from inventory_management.database.repositories.customer_advances_repo import CustomerAdvancesRepo
    monkeypatch.setattr(
        CustomerAdvancesRepo,
        "get_balance",
        lambda self, cid: 1000.0,
    )

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
    from inventory_management.database.repositories.customer_advances_repo import CustomerAdvancesRepo
    monkeypatch.setattr(
        CustomerAdvancesRepo,
        "get_balance",
        lambda self, cid: 1000.0,
    )

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


def test_apply_credit_sale_search_matches_displayed_substrings():
    dlg = receipt_dialog._CustomerMoneyDialog.__new__(receipt_dialog._CustomerMoneyDialog)
    rows = [
        {
            "sale_id": "S-1",
            "doc_no": "INV-2026-00123",
            "date": "2026-06-17",
            "total": 500.0,
            "paid": 250.0,
            "remaining_due": 125.0,
        },
        {
            "sale_id": "S-2",
            "doc_no": "INV-2025-00999",
            "date": "2025-01-01",
            "total": 900.0,
            "paid": 0.0,
            "remaining_due": 900.0,
        },
    ]
    dlg._original_sales = rows
    dlg._get_sale_due = None
    captured = []
    dlg._populate_sales_table = lambda filtered: captured.append(filtered)

    dlg._filter_sales_table("00123")
    dlg._filter_sales_table("2026")
    dlg._filter_sales_table("INV")
    dlg._filter_sales_table("26-00")
    dlg._filter_sales_table("250")
    dlg._filter_sales_table("")

    assert captured[0] == [rows[0]]
    assert captured[1] == [rows[0]]
    assert captured[2] == rows
    assert captured[3] == [rows[0]]
    assert captured[4] == [rows[0]]
    assert captured[5] == rows
