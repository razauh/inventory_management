import sqlite3

from PySide6.QtWidgets import QFrame, QMessageBox

from inventory_management.database.schema import SQL
from inventory_management.modules.expense.category_dialog import CategoryDialog
from inventory_management.modules.expense.controller import ExpenseController


def _controller(qtbot):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SQL)
    controller = ExpenseController(conn)
    qtbot.addWidget(controller.view)
    controller.view.resize(700, 400)
    controller.view.show()
    return controller, conn


def _toasts(widget):
    return widget.findChildren(QFrame, "notificationToast")


def test_expense_add_success_uses_toast_not_blocking_information(qtbot, monkeypatch):
    controller, _conn = _controller(qtbot)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        controller,
        "_open_form",
        lambda initial=None: {
            "description": "Fuel",
            "amount": 12.5,
            "date": "2026-06-21",
            "category_id": None,
        },
    )

    controller._on_add()

    assert calls == []
    assert _toasts(controller.view)[0].title_label.text() == "Saved"


def test_expense_totals_failure_uses_error_toast_not_blocking_information(qtbot, monkeypatch):
    controller, _conn = _controller(qtbot)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        controller.repo,
        "total_by_category",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    controller._refresh_totals()

    assert calls == []
    toast = _toasts(controller.view)[0]
    assert toast.title_label.text() == "Totals"
    assert toast.message_label.text() == "Could not load totals: boom"


def test_expense_delete_confirmation_stays_blocking(qtbot, monkeypatch):
    controller, _conn = _controller(qtbot)
    questions = []
    monkeypatch.setattr(controller, "_selected_expense_id", lambda: 1)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: questions.append(args) or QMessageBox.StandardButton.No,
    )

    controller._on_delete()

    assert questions
    assert questions[0][1] == "Delete"


def test_expense_category_duplicate_stays_blocking(qtbot, monkeypatch):
    controller, _conn = _controller(qtbot)
    dialog = CategoryDialog(controller.view, controller.repo)
    qtbot.addWidget(dialog)
    controller.repo.create_category("Rent")
    dialog.edt_name.setText("Rent")
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))

    dialog._add()

    assert calls
    assert calls[0][1:] == ("Duplicate", "A category with this name already exists.")
