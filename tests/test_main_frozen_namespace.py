import os
import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main


def test_frozen_bootstrap_registers_inventory_management_package(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == "inventory_management" or name.startswith("inventory_management.")
    }
    for name in list(sys.modules):
        if name == "inventory_management" or name.startswith("inventory_management."):
            del sys.modules[name]

    try:
        main._bootstrap_inventory_management_namespace()

        package = sys.modules["inventory_management"]
        assert str(PROJECT_ROOT) in list(getattr(package, "__path__", []))
        controller_module = import_module("inventory_management.modules.customer.controller")
        assert controller_module.__name__ == "inventory_management.modules.customer.controller"
        assert controller_module.__package__ == "inventory_management.modules.customer"
        updater_module = import_module("inventory_management.modules.updater")
        assert updater_module.__name__ == "inventory_management.modules.updater"
        assert hasattr(updater_module, "UpdaterController")
    finally:
        for name in list(sys.modules):
            if name == "inventory_management" or name.startswith("inventory_management."):
                del sys.modules[name]
        sys.modules.update(saved)
        for name, module in saved.items():
            if "." not in name:
                continue
            parent_name, _, child_name = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if parent is not None:
                setattr(parent, child_name, module)


def test_pyinstaller_spec_collects_lazy_app_submodules():
    spec_text = (PROJECT_ROOT / "packaging" / "pyinstaller" / "inventory_management.spec").read_text(
        encoding="utf-8"
    )

    assert "import sys" in spec_text
    assert "for path in (ROOT.parent, ROOT):" in spec_text
    assert "sys.path.insert(0, path_text)" in spec_text
    assert 'collect_submodules("inventory_management.modules", filter=_not_tests)' in spec_text
    assert 'collect_submodules("modules", filter=_not_tests)' in spec_text
    assert 'collect_submodules("inventory_management.database", filter=_not_tests)' in spec_text
    assert 'collect_submodules("database", filter=_not_tests)' in spec_text
    assert 'collect_submodules("inventory_management.utils", filter=_not_tests)' in spec_text
    assert 'collect_submodules("utils", filter=_not_tests)' in spec_text
    assert 'collect_submodules("inventory_management.widgets", filter=_not_tests)' in spec_text
    assert 'collect_submodules("widgets", filter=_not_tests)' in spec_text
    assert 'def _not_tests(module_name):' in spec_text


def test_packaged_import_validation_passes_when_targets_import(monkeypatch, capsys):
    monkeypatch.setattr(main, "_bootstrap_inventory_management_namespace", lambda: None)

    attrs_by_module = {
        module_path: attr_name
        for module_path, attr_name in main._PACKAGED_IMPORT_TARGETS
    }

    def fake_import_module(module_path):
        return SimpleNamespace(**{attrs_by_module[module_path]: object()})

    monkeypatch.setattr(main, "import_module", fake_import_module)

    assert main._validate_packaged_module_imports() == 0
    captured = capsys.readouterr()
    assert "Packaged module import validation passed." in captured.out


def test_packaged_import_validation_reports_failures(monkeypatch, capsys):
    monkeypatch.setattr(main, "_bootstrap_inventory_management_namespace", lambda: None)

    broken_module = main._PACKAGED_IMPORT_TARGETS[0][0]

    def fake_import_module(module_path):
        if module_path == broken_module:
            raise ModuleNotFoundError(module_path)
        attr_name = dict(main._PACKAGED_IMPORT_TARGETS)[module_path]
        return SimpleNamespace(**{attr_name: object()})

    monkeypatch.setattr(main, "import_module", fake_import_module)

    assert main._validate_packaged_module_imports() == 1
    captured = capsys.readouterr()
    assert "Packaged module import validation failed:" in captured.err
    assert broken_module in captured.err


def test_placeholder_text_detection(qtbot):
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    ok_widget = QWidget()
    ok_layout = QVBoxLayout(ok_widget)
    ok_layout.addWidget(QLabel("Products"))
    qtbot.addWidget(ok_widget)

    placeholder = QWidget()
    placeholder_layout = QVBoxLayout(placeholder)
    placeholder_layout.addWidget(QLabel("Products\n\nComing soon..."))
    qtbot.addWidget(placeholder)

    assert main._widget_has_placeholder_text(ok_widget) is False
    assert main._widget_has_placeholder_text(placeholder) is True


def test_desktop_error_log_path_only_for_frozen_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    user_profile = tmp_path / "User"
    desktop = user_profile / "Desktop"
    desktop.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(user_profile))

    assert main._desktop_error_log_path() == desktop / "InventoryManagement-error-log.txt"


def test_module_load_failure_writes_app_data_and_desktop_logs(monkeypatch, tmp_path):
    data_path = tmp_path / "data"
    user_profile = tmp_path / "User"
    desktop = user_profile / "Desktop"
    desktop.mkdir(parents=True)
    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(DATA_PATH=data_path))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("USERPROFILE", str(user_profile))

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        main._log_module_load_failure("Products", "pkg.mod", "Controller", exc)

    app_log = data_path / "logs" / "module_load_failures.log"
    desktop_log = desktop / "InventoryManagement-error-log.txt"
    app_text = app_log.read_text(encoding="utf-8")
    desktop_text = desktop_log.read_text(encoding="utf-8")

    assert "Inventory Management v" in app_text
    assert "[Products] failed to load pkg.mod.Controller: boom" in app_text
    assert "RuntimeError: boom" in app_text
    assert desktop_text == app_text
