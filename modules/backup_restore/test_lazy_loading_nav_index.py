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
        self.widget.setObjectName(f"loaded:{title}")

    def get_widget(self):
        return self.widget


class _FakeBackupController(_FakeController):
    def __init__(self):
        super().__init__(title="Backup & Restore")
        self.menu_registered = False

    def register_menu_actions(self, menu_bar):
        self.menu_registered = True


def test_backup_restore_lazy_load_does_not_mark_earlier_nav_rows_loaded(qtbot, monkeypatch):
    created = []

    def fake_lazy_get(module_path, class_name):
        def factory(*args, **kwargs):
            controller = _FakeController(*args, title=class_name, **kwargs)
            created.append((class_name, controller))
            return controller

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

    backup_index = window._find_module_info_index("Backup & Restore")
    products_index = window._find_module_info_index("Products")

    assert backup_index is not None
    assert products_index == 1
    assert window.modules[0][1] is not None
    assert window.modules[products_index][1] is None

    window._load_module_at_index(backup_index)

    assert window.stack.currentIndex() == backup_index
    assert window.modules[backup_index][0] == "Backup & Restore"
    assert isinstance(window.modules[backup_index][1], _FakeBackupController)
    assert window.modules[products_index][1] is None

    window._load_module_at_index(products_index)

    assert window.stack.currentIndex() == products_index
    assert window.modules[products_index][1] is not None
    assert window.stack.widget(products_index).objectName() == "loaded:ProductController"
    assert [name for name, _controller in created].count("ProductController") == 1


def test_company_info_nav_entry_is_last_after_backup_restore(qtbot, monkeypatch):
    def fake_lazy_get(module_path, class_name):
        return lambda *args, **kwargs: _FakeController(*args, title=class_name, **kwargs)

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

    titles = [title for title, _controller in window.modules]
    assert titles[-2:] == ["Backup & Restore", "Company Info"]
