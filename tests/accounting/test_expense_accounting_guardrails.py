import ast
import subprocess
from pathlib import Path
import pytest

import modules.accounting as accounting
from modules.accounting import AccountingService
from modules.accounting.service import AccountingService as ServiceFacade

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_ACCOUNTING_INTERNALS = (
    "modules.accounting.current_rules",
    "modules.accounting.ledger",
)
TRACKED_PATHS = (
    "modules/expense",
    "database/repositories/expenses_repo.py",
)


def _tracked_module_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", *TRACKED_PATHS],
        check=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        text=True,
    )
    return [
        PROJECT_ROOT / path
        for path in result.stdout.splitlines()
        if path.endswith(".py")
    ]


def _imported_modules(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_expense_modules_do_not_import_accounting_internals():
    bad_imports: list[str] = []

    for path in _tracked_module_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for module_name in _imported_modules(tree):
            if module_name.startswith(FORBIDDEN_ACCOUNTING_INTERNALS):
                bad_imports.append(
                    f"{path.relative_to(PROJECT_ROOT)} imports {module_name}"
                )

    assert bad_imports == []


def test_accounting_service_is_public_expense_facade():
    assert AccountingService is ServiceFacade
    assert ServiceFacade.__module__ == "modules.accounting.service"
    assert "current_rules" not in accounting.__all__


def test_migrated_expense_slices_route_through_accounting_service():
    # Make sure repo calls are delegated to AccountingService
    repo_file = PROJECT_ROOT / "database/repositories/expenses_repo.py"
    repo_content = repo_file.read_text()

    required_delegations = [
        "AccountingService(self.conn).list_expense_rows",
        "AccountingService(self.conn).record_expense_create_event",
        "AccountingService(self.conn).record_expense_update_event",
        "AccountingService(self.conn).record_expense_delete_event",
        "AccountingService(self.conn).get_expense_financial_summary",
        "AccountingService(self.conn).get_expense_screen_category_totals",
        "AccountingService(self.conn).record_expense_category_create_event",
        "AccountingService(self.conn).record_expense_category_update_event",
        "AccountingService(self.conn).record_expense_category_delete_event",
    ]

    for delegation in required_delegations:
        assert delegation in repo_content, f"Expected {delegation} to be called in expenses_repo.py"
