import ast
import importlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PURCHASE_INIT = PROJECT_ROOT / "modules" / "purchase" / "__init__.py"
PURCHASE_CONTROLLER = PROJECT_ROOT / "modules" / "purchase" / "controller.py"


def _tree(path):
    return ast.parse(path.read_text())


def test_purchase_package_does_not_export_legacy_payment_dialog():
    purchase = importlib.import_module("inventory_management.modules.purchase")

    assert "PurchasePaymentDialog" not in purchase.__all__
    assert not hasattr(purchase, "PurchasePaymentDialog")


def test_purchase_controller_does_not_import_legacy_payment_dialog():
    tree = _tree(PURCHASE_CONTROLLER)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "payments":
            imported_names = {alias.name for alias in node.names}
            assert "PurchasePaymentDialog" not in imported_names


def test_purchase_controller_payment_flow_uses_current_payment_form():
    tree = _tree(PURCHASE_CONTROLLER)
    payment_method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_payment"
    )

    imports_payment_form = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "payment_form"
        and any(alias.name == "PaymentForm" for alias in node.names)
        for node in ast.walk(payment_method)
    )
    constructs_payment_form = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PaymentForm"
        for node in ast.walk(payment_method)
    )

    assert imports_payment_form
    assert constructs_payment_form
