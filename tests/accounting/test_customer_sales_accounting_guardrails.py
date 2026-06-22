import ast
import subprocess
from pathlib import Path

import modules.accounting as accounting
from modules.accounting import AccountingService
from modules.accounting.service import AccountingService as ServiceFacade

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_ACCOUNTING_INTERNALS = (
    "modules.accounting.current_rules",
    "modules.accounting.ledger",
)
TRACKED_PATHS = (
    "modules/customer",
    "modules/sales",
    "modules/reporting",
    "modules/dashboard",
    "modules/inventory",
    "database/repositories",
    "widgets",
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


def test_customer_sales_modules_do_not_import_accounting_internals():
    bad_imports: list[str] = []

    for path in _tracked_module_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for module_name in _imported_modules(tree):
            if module_name.startswith(FORBIDDEN_ACCOUNTING_INTERNALS):
                bad_imports.append(
                    f"{path.relative_to(PROJECT_ROOT)} imports {module_name}"
                )

    assert bad_imports == []


def test_accounting_service_is_public_customer_sales_facade():
    assert AccountingService is ServiceFacade
    assert ServiceFacade.__module__ == "modules.accounting.service"
    assert "current_rules" not in accounting.__all__
    assert "ledger" not in accounting.__all__


def test_customer_sales_placeholder_methods_exist():
    from modules.accounting import AccountingNotImplementedError

    svc = AccountingService()
    for method, args in [
        (svc.get_customer_balance, (1,)),
        (svc.get_sale_outstanding, (1,)),
        (svc.get_customer_credit_balance, (1,)),
        (svc.record_customer_payment_event, (None,)),
        (svc.record_sale_return_event, ()),
    ]:
        try:
            method(*args)
            assert False, f"expected AccountingNotImplementedError"
        except AccountingNotImplementedError:
            pass


def test_no_direct_accounting_internal_imports_outside_accounting_module():
    test_customer_sales_modules_do_not_import_accounting_internals()
