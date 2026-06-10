import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QWidget

import main


class _FakeController:
    def __init__(self, *args, title="Module", **kwargs):
        self.title = title
        self.widget = QWidget()

    def get_widget(self):
        return self.widget


class _FakeBackupController(_FakeController):
    def __init__(self):
        super().__init__(title="Backup & Restore")
        self.opened = []
        self.menu_registration_count = 0

    def open_backup_dialog(self):
        self.opened.append("backup")

    def open_restore_dialog(self):
        self.opened.append("restore")

    def register_menu_actions(self, menu_bar):
        self.menu_registration_count += 1


def _window(qtbot, monkeypatch):
    def fake_lazy_get(module_path, class_name):
        def factory(*args, **kwargs):
            return _FakeController(*args, title=class_name, **kwargs)

        return factory

    def fake_import_module(module_path):
        assert module_path == "inventory_management.modules.backup_restore"
        return SimpleNamespace(
            MODULE_TITLE="Backup & Restore",
            create_module=_FakeBackupController,
        )

    monkeypatch.setattr(main, "_lazy_get", fake_lazy_get)
    monkeypatch.setattr(main, "import_module", fake_import_module)

    window = main.MainWindow(conn=object(), current_user={"role": "admin"})
    qtbot.addWidget(window)
    return window


def _file_menu(window):
    for action in window.menuBar().actions():
        menu = action.menu()
        if menu and menu.title().replace("&", "").lower() == "file":
            return menu
    raise AssertionError("File menu was not registered")


def _non_separator_actions(menu):
    return [action for action in menu.actions() if not action.isSeparator()]


def _action(menu, text):
    for action in _non_separator_actions(menu):
        if action.text() == text:
            return action
    raise AssertionError(f"Action not found: {text}")


def test_backup_restore_file_actions_exist_before_nav_lazy_load(qtbot, monkeypatch):
    window = _window(qtbot, monkeypatch)
    backup_index = window._find_module_info_index("Backup & Restore")

    assert backup_index is not None
    assert window.modules[backup_index][1] is None
    assert [action.text() for action in _non_separator_actions(_file_menu(window))] == [
        "Backup Database…",
        "Restore Database…",
    ]


def test_backup_restore_file_action_lazy_loads_module_and_opens_dialog(qtbot, monkeypatch):
    window = _window(qtbot, monkeypatch)
    backup_index = window._find_module_info_index("Backup & Restore")

    _action(_file_menu(window), "Backup Database…").trigger()

    controller = window.modules[backup_index][1]
    assert isinstance(controller, _FakeBackupController)
    assert controller.opened == ["backup"]
    assert window.nav.currentRow() == backup_index


def test_backup_restore_nav_load_does_not_duplicate_file_actions(qtbot, monkeypatch):
    window = _window(qtbot, monkeypatch)
    backup_index = window._find_module_info_index("Backup & Restore")

    window._load_module_at_index(backup_index)

    controller = window.modules[backup_index][1]
    assert isinstance(controller, _FakeBackupController)
    assert controller.menu_registration_count == 0
    assert [action.text() for action in _non_separator_actions(_file_menu(window))] == [
        "Backup Database…",
        "Restore Database…",
    ]
