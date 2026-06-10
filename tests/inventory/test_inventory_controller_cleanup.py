from __future__ import annotations

import ast
import inspect

from inventory_management.modules.inventory import controller as inventory_controller


def test_inventory_controller_does_not_keep_dead_repo_wiring():
    tree = ast.parse(inspect.getsource(inventory_controller))

    imports: set[str] = set()
    init_assigns: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module in {
                "database.repositories.inventory_repo",
                "database.repositories.products_repo",
                "utils.ui_helpers",
                "utils.helpers",
            }:
                imports.update(alias.name for alias in node.names)

        if isinstance(node, ast.ClassDef) and node.name == "InventoryController":
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == "__init__":
                    for stmt in ast.walk(child):
                        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                            targets = []
                            if isinstance(stmt, ast.Assign):
                                targets = stmt.targets
                            else:
                                targets = [stmt.target]
                            for target in targets:
                                if (
                                    isinstance(target, ast.Attribute)
                                    and isinstance(target.value, ast.Name)
                                    and target.value.id == "self"
                                ):
                                    init_assigns.add(target.attr)

    assert not imports
    assert "inv" not in init_assigns
    assert "prod" not in init_assigns
