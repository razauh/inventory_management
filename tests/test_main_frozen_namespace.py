import os
import sys
from importlib import import_module
from pathlib import Path

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


def test_pyinstaller_spec_collects_updater_submodules():
    spec_text = (PROJECT_ROOT / "packaging" / "pyinstaller" / "inventory_management.spec").read_text(
        encoding="utf-8"
    )

    assert 'collect_submodules("inventory_management.modules.updater")' in spec_text
