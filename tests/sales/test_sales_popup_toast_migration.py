import builtins

from PySide6.QtWidgets import QFrame, QMessageBox, QWidget

from inventory_management.modules.sales.controller import SalesController


def _toasts(widget):
    return widget.findChildren(QFrame, "notificationToast")


def test_convert_to_sale_wrong_tab_uses_toast_not_blocking_information(qtbot, monkeypatch):
    view = QWidget()
    qtbot.addWidget(view)
    view.resize(500, 300)
    view.show()

    controller = SalesController.__new__(SalesController)
    controller.view = view
    controller._doc_type = "sale"

    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))

    controller._convert_to_sale()

    assert calls == []
    toast = _toasts(view)[0]
    assert toast.title_label.text() == "Not a quotation"
    assert toast.message_label.text() == "Switch to Quotations to use Convert to Sale."


def test_sale_print_missing_weasyprint_uses_toast_not_blocking_information(qtbot, monkeypatch):
    view = QWidget()
    qtbot.addWidget(view)
    view.resize(500, 300)
    view.show()

    controller = SalesController.__new__(SalesController)
    controller.view = view
    controller._generate_invoice_html_content = lambda _sale_id: "<html></html>"

    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "weasyprint":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    controller._print_sale_invoice("SO-1")

    assert calls == []
    toast = _toasts(view)[0]
    assert toast.title_label.text() == "WeasyPrint Not Available"
    assert toast.message_label.text() == "Please install WeasyPrint: pip install weasyprint"


def test_posted_sale_edit_confirmation_stays_blocking(qtbot, monkeypatch):
    view = QWidget()
    qtbot.addWidget(view)

    controller = SalesController.__new__(SalesController)
    controller.view = view
    controller._db_path = ":memory:"
    controller.repo = type(
        "Repo",
        (),
        {"sale_return_totals": lambda self, _sale_id: {"qty": 0.0, "value": 0.0}},
    )()

    class FakePaymentsRepo:
        def __init__(self, _db_path):
            pass

        def list_by_sale(self, _sale_id):
            return [{"payment_id": 1}]

    questions = []
    monkeypatch.setattr(
        "inventory_management.database.repositories.sale_payments_repo.SalePaymentsRepo",
        FakePaymentsRepo,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: questions.append(args) or QMessageBox.No,
    )

    assert controller._confirm_sale_edit_if_posted({"sale_id": "SO-1"}) is False
    assert questions
    assert questions[0][1] == "Edit Posted Sale?"
