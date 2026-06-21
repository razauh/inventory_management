from PySide6.QtWidgets import QMessageBox, QWidget

from inventory_management.modules.notifications import (
    notify_error,
    notify_info,
    notify_success,
    notify_warning,
)
from inventory_management.utils import ui_helpers


def test_toast_appears_without_message_box(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(500, 300)
    parent.show()
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))

    toast = notify_success(parent, "Saved", "Done.", duration_ms=0)

    assert toast.isVisible()
    assert calls == []


def test_toast_disappears_after_timeout(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(500, 300)
    parent.show()

    toast = notify_info(parent, "Info", "Short.", duration_ms=20)

    qtbot.waitUntil(lambda: not toast.isVisible(), timeout=1000)


def test_toast_levels_have_distinct_styles(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(500, 300)
    parent.show()

    success = notify_success(parent, "Saved", "Done.", duration_ms=0)
    info = notify_info(parent, "Info", "Note.", duration_ms=0)
    warning = notify_warning(parent, "Select", "Pick one.", duration_ms=0)
    error = notify_error(parent, "Error", "Failed.", duration_ms=0)

    styles = {toast.styleSheet() for toast in (success, info, warning, error)}
    assert len(styles) == 4


def test_ui_helper_keeps_validation_blocking(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))

    ui_helpers.info(parent, "Invalid value", "Bad value.")

    assert calls


def test_ui_helper_converts_select_to_toast(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(500, 300)
    parent.show()
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))

    toast = ui_helpers.info(parent, "Select", "Pick a row.")

    assert toast.isVisible()
    assert calls == []


def test_ui_helper_converts_common_feedback_titles(qtbot, monkeypatch):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(500, 300)
    parent.show()
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: calls.append(args))

    for title in ("Export Complete", "Exported", "Nothing to export", "Not found"):
        toast = ui_helpers.info(parent, title, "Done.")
        assert toast.isVisible()

    assert calls == []
