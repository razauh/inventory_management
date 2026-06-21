from PySide6.QtWidgets import QFrame, QMessageBox

from inventory_management.modules.customer.form import CustomerForm
from inventory_management.modules.customer.payment_history_view import _CustomerHistoryDialog


def test_possible_duplicate_customer_uses_toast_not_blocking_warning(qtbot, monkeypatch):
    dlg = CustomerForm(dup_check=lambda _name, _current_id: True)
    qtbot.addWidget(dlg)
    dlg.resize(500, 300)
    dlg.show()
    dlg.name.setText("Acme")
    dlg.contact.setPlainText("555-0100")

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: warnings.append(args))

    payload = dlg.get_payload()

    assert warnings == []
    toasts = dlg.findChildren(QFrame, "notificationToast")
    assert toasts
    assert toasts[0].title_label.text() == "Possible Duplicate"
    assert toasts[0].message_label.text() == (
        "A customer with the same name already exists.\n\n"
        "You can still proceed. Check the existing customer first."
    )
    assert payload["name"] == "Acme"


def test_customer_required_name_stays_blocking(qtbot, monkeypatch):
    dlg = CustomerForm()
    qtbot.addWidget(dlg)
    dlg.contact.setPlainText("555-0100")

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))

    assert dlg.get_payload() is None
    assert warnings
    assert warnings[0][1:] == ("Missing name", "Enter a customer name.")


def test_customer_history_print_failure_uses_toast_not_blocking_warning(qtbot, monkeypatch):
    dlg = _CustomerHistoryDialog(
        customer_id=1,
        history={
            "summary": {"customer_name": "Acme"},
            "timeline": [{"date": "2026-06-21", "kind": "receipt", "amount": 10.0}],
        },
    )
    qtbot.addWidget(dlg)
    dlg.resize(600, 400)
    dlg.show()

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: warnings.append(args))

    def raise_missing_template(*args, **kwargs):
        raise ModuleNotFoundError("missing")

    monkeypatch.setattr(
        "inventory_management.modules.customer.payment_history_view.importlib_resources.files",
        raise_missing_template,
    )

    dlg._on_print_current_tab()

    assert warnings == []
    toasts = dlg.findChildren(QFrame, "notificationToast")
    assert toasts
    assert toasts[0].title_label.text() == "Cannot Print"
    assert toasts[0].message_label.text() == "The customer history print template could not be loaded."
