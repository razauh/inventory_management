from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QListWidget, QListWidgetItem, QStackedWidget
)
from PySide6.QtCore import Qt
from pathlib import Path
import sys
from importlib import import_module
from .constants import APP_NAME, STYLE_FILE
from .database import get_connection
from .modules.base_module import BaseModule

class MainWindow(QMainWindow):
    def __init__(self, conn, current_user: dict):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.conn = conn
        self.user = current_user  # make available to modules

        # ---- Central layout: left nav + stacked pages ----
        central = QWidget(self)
        layout = QVBoxLayout(central)
        self.setCentralWidget(central)

        self.nav = QListWidget()
        self.nav.setMaximumWidth(220)
        self.stack = QStackedWidget()

        from PySide6.QtWidgets import QHBoxLayout
        row = QWidget()
        row_lay = QHBoxLayout(row)
        row_lay.addWidget(self.nav)
        row_lay.addWidget(self.stack, 1)
        layout.addWidget(row, 1)

        self.modules: list[tuple[str, BaseModule]] = []

        # nav wiring
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        # Dashboard (placeholder)
        self.add_placeholder("Dashboard")

        # Products + Inventory
        try:
            ProductController = _lazy_get("inventory_management.modules.product.controller", "ProductController")
            prod = ProductController(self.conn)
            self.add_module("Products", prod)
        except ImportError:
            self.add_placeholder("Products")

        try:
            InventoryController = _lazy_get("inventory_management.modules.inventory.controller", "InventoryController")
            inv = InventoryController(self.conn, current_user=self.user)
            self.add_module("Inventory", inv)
        except ImportError:
            self.add_placeholder("Inventory")

        # Purchases (real)
        try:
            PurchaseController = _lazy_get("inventory_management.modules.purchase.controller", "PurchaseController")
            purchases = PurchaseController(self.conn, current_user=self.user)
            self.add_module("Purchases", purchases)
        except ImportError:
            self.add_placeholder("Purchases")

        # Sales / others...
        
        self.add_placeholder("Quotations")
        self.add_placeholder("Payments")

        # Customers (real module)
        try:
            CustomerController = _lazy_get("inventory_management.modules.customer.controller", "CustomerController")
            customers = CustomerController(self.conn)
            self.add_module("Customers", customers)
        except ImportError as e:
            print(f"[Customers] {e}")
            self.add_placeholder("Customers")

        # Vendors (real module)
        try:
            VendorController = _lazy_get("inventory_management.modules.vendor.controller", "VendorController")
            vendors = VendorController(self.conn)
            self.add_module("Vendors", vendors)
        except ImportError:
            self.add_placeholder("Vendors")

        try:
            SalesController = _lazy_get("inventory_management.modules.sales.controller", "SalesController")
            sales = SalesController(self.conn, current_user=self.user)
            self.add_module("Sales", sales)
        except ImportError as e:
            print(f"[Sales] {e}")
            self.add_placeholder("Sales")


        # Expense/Reporting/Admin/etc.
        self.add_placeholder("Expense")
        self.add_placeholder("Reporting")
        if (self.user and self.user.get("role") == "admin"):
            self.add_placeholder("Users")
            self.add_placeholder("System Logs")
        self.add_placeholder("Printing")

    def add_module(self, title: str, module: BaseModule):
        page = module.get_widget()
        item = QListWidgetItem(title)
        self.nav.addItem(item)
        self.stack.addWidget(page)
        self.modules.append((title, module))

    def add_placeholder(self, title: str):
        from PySide6.QtWidgets import QLabel
        from .utils.ui_helpers import wrap_center
        placeholder = wrap_center(QLabel(f"{title}\n\nComing soon..."))
        item = QListWidgetItem(title)
        self.nav.addItem(item)
        self.stack.addWidget(placeholder)

def load_qss() -> str:
    qss = ""
    f = Path(__file__).resolve().parent / STYLE_FILE
    if f.exists():
        qss = f.read_text(encoding="utf-8")
    return qss

def _lazy_get(name: str, attr: str):
    """
    Import a module by name and fetch an attribute from it, with with a clear error if missing.
    """
    try:
        mod = import_module(name)
    except Exception as e:
        raise ImportError(f"Failed to import module '{name}': {e}") from e
    try:
        return getattr(mod, attr)
    except AttributeError as e:
        raise ImportError(f"'{attr}' not found in module '{name}'.") from e

def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # DB connection (ensure schema, etc.)
    conn = get_connection()

    # ---- Lazy import controllers (no top-level imports that can trigger circulars)
    LoginController = _lazy_get("inventory_management.modules.login.controller", "LoginController")

    # ---- Login first (uses conn if needed)
    login = LoginController(conn)
    user = login.prompt()
    if not user:
        return  # user cancelled / failed login

    # Optional style
    qss = load_qss()
    if qss:
        app.setStyleSheet(qss)

    # Window
    win = MainWindow(conn, current_user=user)

    # Show UI
    win.resize(1200, 720)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
