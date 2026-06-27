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


def _tracked_module_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "modules"],
        check=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        text=True,
    )
    return [
        PROJECT_ROOT / path
        for path in result.stdout.splitlines()
        if path.endswith(".py") and not path.startswith("modules/accounting/")
    ]


def _imported_modules(tree: ast.AST, file_path: Path) -> set[str]:
    imports: set[str] = set()
    try:
        rel_path = file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel_path = file_path

    dir_parts = [p for p in rel_path.parent.parts if p and p != "."]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                slice_idx = len(dir_parts) - node.level + 1
                base_parts = dir_parts[:slice_idx]
                mod_parts = list(base_parts)
                if node.module:
                    mod_parts.extend(node.module.split("."))
                imports.add(".".join(mod_parts))
            elif node.module:
                imports.add(node.module)
    return imports


def test_vendor_purchase_modules_do_not_import_accounting_internals():
    bad_imports: list[str] = []

    for path in _tracked_module_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module_name in _imported_modules(tree, path):
            if module_name.startswith(FORBIDDEN_ACCOUNTING_INTERNALS):
                bad_imports.append(
                    f"{path.relative_to(PROJECT_ROOT)} imports {module_name}"
                )

    assert bad_imports == []


def test_accounting_service_is_public_facade():
    assert AccountingService is ServiceFacade
    assert ServiceFacade.__module__ == "modules.accounting.service"
    assert "current_rules" not in accounting.__all__
    assert "ledger" not in accounting.__all__


def test_migrated_vendor_purchase_slices_route_through_accounting_service():
    required_routes = {
        "database/repositories/purchases_repo.py": [
            "self.accounting.get_purchase_financials",
            "self.accounting.get_purchase_remaining_due_header",
            "self.accounting.get_purchase_return_values",
            "self.accounting.get_purchase_return_totals",
            "self.accounting.get_purchase_returnable_quantities",
            "self.accounting.record_purchase_inventory_event",
            "self.accounting.record_purchase_return_event",
        ],
        "database/repositories/purchase_payments_repo.py": [
            "AccountingService(self.conn).record_vendor_payment_event",
        ],
        "database/repositories/vendor_advances_repo.py": [
            "self.accounting.get_purchase_remaining_due_header",
            "self.accounting.record_vendor_advance_event",
        ],
        "modules/purchase/controller.py": [
            "self.accounting.get_purchase_invoice_financials",
            "self.accounting.get_purchase_payment_summary",
            "self.accounting.record_vendor_payment_event",
            "self.accounting.record_purchase_return_event",
        ],
        "modules/purchase/return_form.py": [
            "self.accounting.get_purchase_financials",
            "self.accounting.preview_purchase_return_effect",
        ],
        "modules/reporting/financial_reports.py": [
            "self.accounting.get_ap_summary",
            "self.accounting.get_payment_activity",
        ],
        "modules/reporting/payment_reports.py": [
            "self.accounting.get_payment_activity",
        ],
        "modules/reporting/vendor_aging_reports.py": [
            "self.accounting.get_vendor_aging",
        ],
        "widgets/invoice_preview.py": [
            "AccountingService(self.conn).get_purchase_invoice_financials",
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
    test_vendor_purchase_modules_do_not_import_accounting_internals()


def test_guardrails_reject_relative_imports_of_accounting_internals():
    # Verify relative imports are correctly resolved and flagged by _imported_modules
    code = "from ..accounting.current_rules.vendor_rules import get_vendor_statement"
    tree = ast.parse(code)
    file_path = PROJECT_ROOT / "modules/vendor/controller.py"
    resolved = _imported_modules(tree, file_path)
    assert "modules.accounting.current_rules.vendor_rules" in resolved


def test_guardrails_scan_fallback_vendor_controller_import_path():
    vendor_controller_path = PROJECT_ROOT / "modules/vendor/controller.py"
    assert vendor_controller_path.exists()

    tracked_files = _tracked_module_python_files()
    assert vendor_controller_path in tracked_files

