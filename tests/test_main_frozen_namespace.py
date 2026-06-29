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

    names_to_clear = [
        "inventory_management",
        "inventory_management.modules.customer",
        "inventory_management.modules.customer.controller",
        "inventory_management.modules",
    ]
    for name in names_to_clear:
        monkeypatch.delitem(sys.modules, name, raising=False)

    main._bootstrap_inventory_management_namespace()

    package = sys.modules["inventory_management"]
    assert str(PROJECT_ROOT) in list(getattr(package, "__path__", []))
    controller_module = import_module("inventory_management.modules.customer.controller")
    assert controller_module.__name__ == "inventory_management.modules.customer.controller"
    assert controller_module.__package__ == "inventory_management.modules.customer"
