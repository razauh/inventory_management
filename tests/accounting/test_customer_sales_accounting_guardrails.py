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


def test_migrated_customer_sales_slices_route_through_accounting_service():
    required_routes = {
        "database/repositories/sales_repo.py": [
            "self.accounting.get_sale_totals",
            "self.accounting.get_sale_financial_summary",
            "self.accounting.recalculate_sale_payment_status",
            "self.accounting.record_sale_return_event",
            "self.accounting.record_sale_inventory_event",
            "self.accounting.get_sale_return_totals",
        ],
        "database/repositories/sale_payments_repo.py": [
            "get_sale_payment_history",
            "get_latest_sale_payment",
            "get_customer_payment_history",
            "record_customer_payment_event",
            "update_customer_payment_state",
            "reopen_customer_payment_state",
        ],
        "database/repositories/customer_advances_repo.py": [
            "get_customer_credit_balance",
            "list_customer_credit_ledger",
            "record_customer_credit_event",
            "record_customer_credit_application_event",
        ],
        "database/repositories/customers_repo.py": [
            "self.accounting.get_customer_receivable_summary",
        ],
        "database/repositories/reporting_repo.py": [
            "self.accounting",
        ],
        "database/repositories/dashboard_repo.py": [
            "self.accounting",
        ],
        "modules/sales/controller.py": [
            "self.accounting.get_sale_totals",
            "self.accounting.get_sale_financial_summary",
            "self.accounting.get_sale_invoice_financials",
            "self.accounting.get_quotation_financials",
        ],
        "modules/customer/controller.py": [
            "self.accounting.list_customer_sale_summaries",
            "list_customer_sale_summaries",
        ],
        "modules/dashboard/controller.py": [
            "self.accounting.get_sales_dashboard_metrics",
        ],
    }

    missing: list[str] = []
    for rel_path, snippets in required_routes.items():
        source = (PROJECT_ROOT / rel_path).read_text()
        for snippet in snippets:
            if snippet not in source:
                missing.append(f"{rel_path} missing {snippet}")

    assert missing == []


def test_no_direct_accounting_internal_imports_outside_accounting_module():
    test_customer_sales_modules_do_not_import_accounting_internals()
