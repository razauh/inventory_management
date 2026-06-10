import builtins
import importlib
import sys

import pytest


PURCHASE_PACKAGE = "inventory_management.modules.purchase"
PURCHASE_PREFIX = f"{PURCHASE_PACKAGE}."


def _is_purchase_relative_view_import(name, globals, level):
    package = (globals or {}).get("__package__")
    return level == 1 and package == PURCHASE_PACKAGE and name == "view"


@pytest.fixture()
def isolated_purchase_package():
    saved = {
        name: module
        for name, module in sys.modules.items()
        if name == PURCHASE_PACKAGE or name.startswith(PURCHASE_PREFIX)
    }
    for name in saved:
        sys.modules.pop(name, None)

    yield

    for name in list(sys.modules):
        if name == PURCHASE_PACKAGE or name.startswith(PURCHASE_PREFIX):
            sys.modules.pop(name, None)
    sys.modules.update(saved)


def test_purchase_package_import_is_tolerant_only_when_pyside6_is_missing(
    monkeypatch, isolated_purchase_package
):
    original_import = builtins.__import__

    def import_without_pyside6(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PySide6" or name.startswith("PySide6."):
            raise ModuleNotFoundError("No module named 'PySide6'", name="PySide6")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_without_pyside6)

    purchase = importlib.import_module(PURCHASE_PACKAGE)

    assert purchase.__all__
    for export_name in purchase.__all__:
        assert getattr(purchase, export_name) is None


def test_purchase_package_import_does_not_mask_non_qt_import_errors(
    monkeypatch, isolated_purchase_package
):
    original_import = builtins.__import__

    def import_with_broken_purchase_view(name, globals=None, locals=None, fromlist=(), level=0):
        if name == f"{PURCHASE_PACKAGE}.view" or _is_purchase_relative_view_import(
            name, globals, level
        ):
            raise ImportError("broken purchase view")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_with_broken_purchase_view)

    with pytest.raises(ImportError, match="broken purchase view"):
        importlib.import_module(PURCHASE_PACKAGE)


def test_purchase_package_import_does_not_mask_runtime_errors(
    monkeypatch, isolated_purchase_package
):
    original_import = builtins.__import__

    def import_with_runtime_failure(name, globals=None, locals=None, fromlist=(), level=0):
        if name == f"{PURCHASE_PACKAGE}.view" or _is_purchase_relative_view_import(
            name, globals, level
        ):
            raise RuntimeError("purchase view crashed")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_with_runtime_failure)

    with pytest.raises(RuntimeError, match="purchase view crashed"):
        importlib.import_module(PURCHASE_PACKAGE)
