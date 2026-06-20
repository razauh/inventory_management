from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_INIT = PROJECT_ROOT / "modules" / "inventory" / "__init__.py"
INVENTORY_CONTROLLER = PROJECT_ROOT / "modules" / "inventory" / "controller.py"


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text())


def test_inventory_package_does_not_export_legacy_inventory_view():
    tree = _tree(INVENTORY_INIT)

    imported_names: set[str] = set()
    exported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    exported_names = {
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }

    assert "InventoryView" not in imported_names
    assert "InventoryView" not in exported_names


def test_inventory_controller_uses_active_inventory_widgets_only():
    tree = _tree(INVENTORY_CONTROLLER)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "view",
            "model",
            "transactions",
            "stock_valuation",
            "database.repositories.inventory_repo",
        }:
            imported_names.update(alias.name for alias in node.names)

    assert imported_names == {
        "InventoryView",
        "LowInventoryTableModel",
        "TransactionsTableModel",
        "TransactionsView",
        "StockValuationWidget",
        "InventoryRepo",
    }
