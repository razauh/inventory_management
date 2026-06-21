import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from inventory_management.modules.customer.controller import CustomerController


def test_customer_statement_print_opens_preview(monkeypatch):
    class FakeHistoryService:
        def __init__(self, db_path):
            pass

        def full_history(self, customer_id):
            return {
                "summary": {"customer_name": "Customer A"},
                "timeline": [{"date": "2026-06-21", "kind": "receipt", "amount": 10.0}],
            }

    class FakeHTML:
        def __init__(self, *, string):
            self.string = string

        def write_pdf(self, path, stylesheets=None):
            Path(path).write_bytes(b"%PDF-1.4\n%%EOF\n")

    class FakeCSS:
        def __init__(self, *args, **kwargs):
            pass

    fake_weasyprint = ModuleType("weasyprint")
    fake_weasyprint.HTML = FakeHTML
    fake_weasyprint.CSS = FakeCSS
    monkeypatch.setitem(sys.modules, "weasyprint", fake_weasyprint)
    monkeypatch.setattr(
        "inventory_management.modules.customer.history.CustomerHistoryService",
        FakeHistoryService,
    )

    shown = {}
    monkeypatch.setattr(
        "inventory_management.modules.customer.controller.show_invoice_preview",
        lambda parent, path, title: shown.update({"path": path, "title": title}),
    )

    controller = CustomerController.__new__(CustomerController)
    controller.view = SimpleNamespace()
    controller._preflight = lambda require_file_db=True: (7, "/tmp/test.db")
    controller.repo = SimpleNamespace(
        get=lambda customer_id: SimpleNamespace(
            name="Customer A",
            contact_info="contact",
            address="address",
        )
    )

    controller._on_history_print()

    assert shown["title"] == "Customer Statement 7"
    assert Path(shown["path"]).exists()
    assert Path(shown["path"]).name == "customer_7.pdf"
