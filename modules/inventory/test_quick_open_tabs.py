import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))

from inventory_management.modules.inventory.controller import InventoryController

import main


class _FakeTabs:
    def __init__(self, current_index=0, count=3):
        self.current_index = current_index
        self._count = count

    def count(self):
        return self._count

    def setCurrentIndex(self, index):
        self.current_index = index


class _FakeWidget:
    def __init__(self, tabs):
        self.tabs = tabs

    def findChild(self, _widget_type):
        return self.tabs


class _FallbackController:
    def __init__(self, tabs):
        self.widget = _FakeWidget(tabs)

    def get_widget(self):
        return self.widget


class _FakeNav:
    def __init__(self):
        self.current_row = None

    def setCurrentRow(self, index):
        self.current_row = index


class _FakeWindow:
    def __init__(self, controller):
        self.nav = _FakeNav()
        self.modules = [("Inventory", controller)]

    def _find_module_index(self, title):
        return 0 if title == "Inventory" else None


def test_inventory_controller_selects_active_tabs_by_name():
    controller = SimpleNamespace(tabs=_FakeTabs(current_index=1))

    assert InventoryController.select_tab(controller, "valuation") is True
    assert controller.tabs.current_index == 0

    assert InventoryController.select_tab(controller, "transactions") is True
    assert controller.tabs.current_index == 1

    assert InventoryController.select_tab(controller, "adjustments") is True
    assert controller.tabs.current_index == 2


def test_inventory_quick_open_fallback_matches_active_tabs():
    tabs = _FakeTabs(current_index=1)
    window = _FakeWindow(_FallbackController(tabs))

    main.MainWindow.open_inventory_sub(window, "valuation")
    assert window.nav.current_row == 0
    assert tabs.current_index == 0

    main.MainWindow.open_inventory_sub(window, "transactions")
    assert tabs.current_index == 1

    main.MainWindow.open_inventory_sub(window, "adjustments")
    assert tabs.current_index == 2
